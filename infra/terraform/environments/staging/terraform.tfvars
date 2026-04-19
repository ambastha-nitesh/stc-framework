region              = "us-east-1"
service_name        = "stc-framework"
image_tag           = "staging-latest"
deployed_subsystems = "service,litellm,redis,launchdarkly,otlp,qdrant,presidio"
cidr_block          = "10.41.0.0/16"
az_count            = 2

deletion_protection = true

service_min_replicas = 2
service_max_replicas = 6

rds_min_acu = 0.5
rds_max_acu = 4.0

redis_node_type    = "cache.t4g.medium"
redis_num_replicas = 1

s3_audit_object_lock_days = 365

manage_github_oidc_provider = false
github_repository           = "ambastha-nitesh/stc-framework"

api_domain_name     = ""
api_certificate_arn = ""
waf_web_acl_arn     = ""

alarm_notification_arn = ""
