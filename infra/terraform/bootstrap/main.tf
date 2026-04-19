# Bootstrap — state backend only. Run ONCE per AWS account + region,
# BEFORE the main root stack. Uses local state (the bucket being
# created cannot store its own state).
#
# Flow:
#   cd infra/terraform/bootstrap
#   terraform init && terraform apply
#   # Then configure backend.tf in the root stack to point at these
#   # resources and run `terraform init` in infra/terraform/.

terraform {
  required_version = ">= 1.6, < 2.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  description = "AWS region for the state backend."
  type        = string
  default     = "us-east-1"
}

variable "service" {
  description = "Service name used in bucket + table names."
  type        = string
  default     = "stc-framework"
}

data "aws_caller_identity" "this" {}

locals {
  bucket_name = "${var.service}-tfstate-${data.aws_caller_identity.this.account_id}-${var.region}"
  table_name  = "${var.service}-tfstate-lock"
  tags = {
    managed_by = "terraform"
    service    = var.service
    purpose    = "tfstate"
  }
}

resource "aws_kms_key" "tfstate" {
  description             = "Encrypts Terraform state for ${var.service}."
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = local.tags
}

resource "aws_kms_alias" "tfstate" {
  name          = "alias/${var.service}-tfstate"
  target_key_id = aws_kms_key.tfstate.key_id
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.bucket_name
  tags   = local.tags
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.tfstate.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonTLS"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.tfstate.arn,
        "${aws_s3_bucket.tfstate.arn}/*",
      ]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_dynamodb_table" "lock" {
  name         = local.table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"
  attribute {
    name = "LockID"
    type = "S"
  }
  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.tfstate.arn
  }
  tags = local.tags
}

output "state_bucket" {
  value       = aws_s3_bucket.tfstate.bucket
  description = "Configure this as the ``bucket`` arg in the root stack's backend."
}

output "state_table" {
  value       = aws_dynamodb_table.lock.name
  description = "Configure this as the ``dynamodb_table`` arg in the root stack's backend."
}

output "kms_key_arn" {
  value = aws_kms_key.tfstate.arn
}
