variable "name_prefix" {
  type = string
}

variable "manage_oidc_provider" {
  description = "Create the GitHub OIDC provider. Only ONE workspace per account should set this true."
  type        = bool
  default     = false
}

variable "github_subject_patterns" {
  description = "``token.actions.githubusercontent.com:sub`` match patterns that may assume the deploy role."
  type        = list(string)
  default     = ["repo:ambastha-nitesh/stc-framework:ref:refs/heads/main"]
}

variable "secret_arns" {
  description = "Secrets Manager ARNs the deploy role + task roles may read."
  type        = list(string)
  default     = ["*"]
}

variable "kms_key_arns" {
  description = "KMS key ARNs the task execution role may Decrypt + task role may GenerateDataKey against."
  type        = list(string)
  default     = ["*"]
}

variable "s3_audit_bucket_arn" {
  description = "Audit S3 bucket ARN; task role may PutObject (with Object Lock) here."
  type        = string
  default     = "*"
}

variable "amp_workspace_arns" {
  description = "AMP workspace ARNs the task role may RemoteWrite to."
  type        = list(string)
  default     = ["*"]
}

variable "tfstate_bucket" {
  description = "S3 bucket holding Terraform state. CI deploy role reads/writes."
  type        = string
}

variable "tfstate_lock_arn" {
  description = "DynamoDB lock table ARN."
  type        = string
}
