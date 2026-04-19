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

variable "recovery_window_days" {
  description = "Days a deleted secret remains recoverable (0 = immediate delete)."
  type        = number
  default     = 7
}
