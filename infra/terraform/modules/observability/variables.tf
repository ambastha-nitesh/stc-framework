variable "name_prefix" { type = string }
variable "sns_topic_arn" {
  type    = string
  default = ""
}

variable "alb_dimension" {
  description = "Value of the ``LoadBalancer`` dimension on ALB metrics (e.g. ``app/my-alb/abc123``)."
  type        = string
  default     = ""
}

variable "ecs_cluster_name" { type = string }
variable "ecs_service_name" { type = string }
variable "rds_cluster_identifier" { type = string }
variable "redis_replication_group_id" { type = string }

variable "min_running_tasks" {
  type    = number
  default = 2
}
