variable "name_prefix" {
  type = string
}

variable "repos" {
  description = "Map of repo short-name -> purpose description."
  type        = map(string)
}

variable "kms_key_arn" {
  description = "KMS key for ECR image encryption."
  type        = string
}

variable "image_tag_mutability" {
  description = "IMMUTABLE in prod, MUTABLE in dev/staging (for rapid iteration)."
  type        = string
  default     = "MUTABLE"
  validation {
    condition     = contains(["MUTABLE", "IMMUTABLE"], var.image_tag_mutability)
    error_message = "image_tag_mutability must be MUTABLE or IMMUTABLE."
  }
}
