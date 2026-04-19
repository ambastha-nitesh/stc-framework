variable "name_prefix" {
  type = string
}

variable "kms_key_arn" {
  description = "KMS CMK for server-side bucket encryption."
  type        = string
}

variable "object_lock_days" {
  description = "COMPLIANCE-mode default retention period in days."
  type        = number
  default     = 2190
}

variable "deletion_protection" {
  description = "When true (prod), ``force_destroy`` is false so ``terraform destroy`` leaves the bucket alone."
  type        = bool
  default     = true
}
