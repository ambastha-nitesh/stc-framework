variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "kms_key_arn" { type = string }

variable "master_username" {
  type    = string
  default = "stc"
}

variable "database_name" {
  type    = string
  default = "stc_history"
}

variable "min_acu" {
  type    = number
  default = 0.5
}

variable "max_acu" {
  type    = number
  default = 2.0
}

variable "instance_count" {
  type    = number
  default = 1
}

variable "backup_retention_days" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  type    = bool
  default = false
}
