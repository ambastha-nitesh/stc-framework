variable "name_prefix" { type = string }
variable "region" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "cluster_arn" { type = string }
variable "ecr_repo_url" { type = string }
variable "task_execution_role_arn" { type = string }
variable "task_role_arn" { type = string }

variable "image_tag" {
  type    = string
  default = "v1.11.0"
}

variable "cpu" {
  type    = number
  default = 1024
}

variable "memory" {
  type    = number
  default = 2048
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "namespace" {
  description = "Cloud Map private DNS namespace (e.g. stc.internal)."
  type        = string
  default     = "stc.internal"
}

variable "create_namespace" {
  description = "Create the namespace. Only ONE module per VPC should do this; others look it up."
  type        = bool
  default     = true
}
