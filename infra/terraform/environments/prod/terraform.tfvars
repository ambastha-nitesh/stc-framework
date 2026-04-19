region              = "us-east-1"
service_name        = "stc-framework"
image_tag           = "prod-latest"
deployed_subsystems = "service,litellm,redis,launchdarkly,otlp,qdrant,presidio,langfuse"
cidr_block          = "10.42.0.0/16"
az_count            = 3

deletion_protection = true

service_min_replicas = 3
service_max_replicas = 10

rds_min_acu = 1.0
rds_max_acu = 8.0

redis_node_type    = "cache.r7g.large"
redis_num_replicas = 2

s3_audit_object_lock_days = 2190 # 6 years — SEC 17a-4 / FINRA 4511

manage_github_oidc_provider = false
github_repository           = "ambastha-nitesh/stc-framework"

# Override before first apply — production MUST have a custom domain
# with an ACM cert and a WAFv2 ACL attached.
api_domain_name     = ""
api_certificate_arn = ""
waf_web_acl_arn     = ""

# SNS topic ARN for alarm notifications. MUST be set before first apply.
alarm_notification_arn = ""
