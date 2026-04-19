variable "region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "service_name" {
  description = "Short service name used in resource name prefixes."
  type        = string
  default     = "stc-framework"
}

variable "image_tag" {
  description = "ECR image tag for the STC framework container. Passed by CI as ``<sha>-<subshash>``."
  type        = string
}

variable "deployed_subsystems" {
  description = "Comma-separated list of extras baked into the image. Informational; mirrors the Dockerfile ARG so Terraform can surface it as a label."
  type        = string
  default     = "service,litellm,redis,launchdarkly,otlp"
}

variable "cidr_block" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Number of Availability Zones to spread subnets across."
  type        = number
  default     = 2
}

variable "alarm_notification_arn" {
  description = "SNS topic ARN that receives CloudWatch alarm notifications."
  type        = string
  default     = ""
}

variable "deletion_protection" {
  description = "Enforce deletion protection on RDS, ElastiCache, and the audit bucket."
  type        = bool
  default     = false
}

variable "service_min_replicas" {
  description = "Minimum ECS service replicas for the STC framework task."
  type        = number
  default     = 2
}

variable "service_max_replicas" {
  description = "Maximum ECS service replicas for the STC framework task."
  type        = number
  default     = 10
}

variable "rds_min_acu" {
  description = "Aurora Serverless v2 minimum ACUs."
  type        = number
  default     = 0.5
}

variable "rds_max_acu" {
  description = "Aurora Serverless v2 maximum ACUs."
  type        = number
  default     = 2.0
}

variable "redis_node_type" {
  description = "ElastiCache Redis node type."
  type        = string
  default     = "cache.t4g.small"
}

variable "redis_num_replicas" {
  description = "Number of replica nodes in the Redis replication group."
  type        = number
  default     = 1
}

variable "s3_audit_object_lock_days" {
  description = "Object Lock retention period in days for the audit bucket (COMPLIANCE mode)."
  type        = number
  default     = 2190 # 6 years — GDPR / SEC 17a-4 minimum
}

variable "manage_github_oidc_provider" {
  description = "Whether this workspace should create the GitHub OIDC provider (only one workspace per account should set this true)."
  type        = bool
  default     = false
}

variable "github_repository" {
  description = "owner/repo format; restricts the OIDC deploy role's trust policy."
  type        = string
  default     = "ambastha-nitesh/stc-framework"
}

variable "api_domain_name" {
  description = "Custom domain for the public API Gateway endpoint. Leave empty to skip."
  type        = string
  default     = ""
}

variable "api_certificate_arn" {
  description = "ACM certificate ARN for ``api_domain_name``. Required when the domain is set."
  type        = string
  default     = ""
}

variable "waf_web_acl_arn" {
  description = "Optional WAFv2 Web ACL ARN to associate with the API Gateway."
  type        = string
  default     = ""
}
