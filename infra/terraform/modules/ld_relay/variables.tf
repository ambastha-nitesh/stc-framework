variable "name_prefix" { type = string }
variable "region" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "cluster_arn" { type = string }
variable "ecr_repo_url" { type = string }
variable "namespace_id" {
  description = "Cloud Map namespace ID (ns-xxx) to register the service record in."
  type        = string
}

variable "namespace_name" {
  description = "Cloud Map namespace name (e.g. stc.internal). Used to build the relay URL."
  type        = string
}
variable "task_execution_role_arn" { type = string }
variable "task_role_arn" { type = string }
variable "ld_sdk_key_secret_arn" { type = string }

variable "image_tag" {
  type    = string
  default = "7"
}

variable "cpu" {
  type    = number
  default = 512
}

variable "memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 30
}
