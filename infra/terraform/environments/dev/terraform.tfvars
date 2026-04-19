region              = "us-east-1"
service_name        = "stc-framework"
image_tag           = "main-latest"
deployed_subsystems = "service,litellm,redis,launchdarkly,otlp"
cidr_block          = "10.40.0.0/16"
az_count            = 2

deletion_protection = false

service_min_replicas = 1
service_max_replicas = 3

rds_min_acu = 0.5
rds_max_acu = 2.0

redis_node_type    = "cache.t4g.small"
redis_num_replicas = 0

s3_audit_object_lock_days = 30 # short retention in dev for easy teardown

manage_github_oidc_provider = true
github_repository           = "ambastha-nitesh/stc-framework"

# Leave blank to use the default execute-api endpoint in dev.
api_domain_name     = ""
api_certificate_arn = ""
waf_web_acl_arn     = ""

alarm_notification_arn = ""
