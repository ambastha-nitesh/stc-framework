variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "kms_key_arn" { type = string }
variable "auth_token_secret_arn" { type = string }

variable "node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "num_replicas" {
  type    = number
  default = 1
}

variable "snapshot_retention_days" {
  type    = number
  default = 1
}
