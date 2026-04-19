variable "name_prefix" {
  type = string
}

variable "kms_key_arn" {
  description = "KMS CMK for Secrets Manager encryption."
  type        = string
}

variable "specs" {
  description = "Map of logical secret name -> description."
  type        = map(string)
}

variable "terraform_managed_names" {
  description = "Subset of ``specs`` keys whose values are written by other Terraform resources (elasticache auth_token, composed redis_url). Placeholder versions are skipped for these to avoid two resources fighting over AWSCURRENT."
  type        = list(string)
  default     = []
}

variable "recovery_window_days" {
  description = "Days a deleted secret remains recoverable (0 = immediate delete)."
  type        = number
  default     = 7
}
