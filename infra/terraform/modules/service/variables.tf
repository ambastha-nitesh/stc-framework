variable "name_prefix" { type = string }
variable "environment" { type = string }
variable "region" { type = string }
variable "deployed_subsystems" { type = string }

variable "subnet_ids" { type = list(string) }
variable "security_group_id" { type = string }
variable "cluster_arn" { type = string }
variable "cluster_name" { type = string }

variable "ecr_repo_url" { type = string }
variable "image_tag" { type = string }

variable "task_execution_role_arn" { type = string }
variable "task_role_arn" { type = string }

variable "target_group_arn" {
  description = "Internal ALB target group — tasks register on :8000."
  type        = string
}

variable "ld_relay_url" { type = string }

variable "secret_arns" {
  description = "Map of logical secret key -> Secrets Manager ARN. Only specific keys materialise into env vars; see locals.secrets_list."
  type        = map(string)
}

variable "amp_remote_write_endpoint" {
  description = "AMP workspace remote-write URL (e.g. https://aps-workspaces.us-east-1.amazonaws.com/workspaces/ws-.../api/v1/remote_write)."
  type        = string
}

variable "adot_image_url" { type = string }
variable "adot_image_tag" {
  type    = string
  default = "latest"
}

variable "presidio_image_url" {
  type    = string
  default = "mcr.microsoft.com/presidio-analyzer"
}
variable "presidio_image_tag" {
  type    = string
  default = "latest"
}

variable "cpu" {
  type    = number
  default = 1024
}
variable "memory" {
  type    = number
  default = 2048
}

variable "min_replicas" {
  type    = number
  default = 2
}
variable "max_replicas" {
  type    = number
  default = 10
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "log_level" {
  type    = string
  default = "INFO"
}
