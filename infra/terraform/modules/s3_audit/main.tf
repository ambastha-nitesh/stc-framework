# S3 bucket for WORM audit logs. Object Lock is enabled AT BUCKET
# CREATION — it cannot be retrofitted — with COMPLIANCE mode so even
# the bucket owner cannot shorten retention. This aligns with SEC
# 17a-4(f) / FINRA 4511 WORM requirements.
#
# The audit-sync sidecar in the STC task uploads sealed JSONL files
# here with x-amz-object-lock-retain-until-date headers.

resource "aws_s3_bucket" "audit" {
  bucket              = "${var.name_prefix}-audit"
  object_lock_enabled = true

  # Prod workspaces set this false; dev may leave true to rebuild easily.
  force_destroy = !var.deletion_protection

  tags = { Name = "${var.name_prefix}-audit", purpose = "worm-audit" }
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.object_lock_days
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = var.kms_key_arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Deny non-TLS traffic and non-KMS uploads at the bucket policy level.
resource "aws_s3_bucket_policy" "audit" {
  bucket = aws_s3_bucket.audit.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyNonTLS"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.audit.arn, "${aws_s3_bucket.audit.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "DenyNonKmsPut"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.audit.arn}/*"
        Condition = {
          StringNotEquals = {
            "s3:x-amz-server-side-encryption" = "aws:kms"
          }
        }
      },
    ]
  })
}

# Transition objects that are out of the object-lock retention window
# to Glacier Deep Archive. Keeps current-gen data hot while shrinking
# long-tail storage cost.
resource "aws_s3_bucket_lifecycle_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    id     = "archive-after-lock-expiry"
    status = "Enabled"
    filter {}

    transition {
      days          = var.object_lock_days
      storage_class = "DEEP_ARCHIVE"
    }
  }
}
