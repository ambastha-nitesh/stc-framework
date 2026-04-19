variable "name_prefix" { type = string }
variable "subnet_ids" { type = list(string) }
variable "vpc_link_security_group_id" { type = string }
variable "alb_listener_arn" {
  description = "Internal ALB listener ARN that API Gateway proxies to via VPC Link."
  type        = string
}

variable "domain_name" {
  type    = string
  default = ""
}
variable "acm_certificate_arn" {
  type    = string
  default = ""
}
variable "waf_web_acl_arn" {
  type    = string
  default = ""
}

variable "throttle_rate" {
  type    = number
  default = 100
}
variable "throttle_burst" {
  type    = number
  default = 200
}

variable "log_retention_days" {
  type    = number
  default = 30
}
