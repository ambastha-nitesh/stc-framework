locals {
  environment = terraform.workspace
  name_prefix = "${var.service_name}-${local.environment}"

  # Plural resources use for_each over these maps.
  kms_purposes = {
    secrets     = "Encrypts Secrets Manager payloads"
    s3_audit    = "Encrypts the WORM audit bucket"
    rds         = "Encrypts Aurora storage + backups"
    elasticache = "Encrypts Redis at rest + in transit"
  }

  ecr_repos = {
    "stc-framework"    = "STC framework service image"
    "ld-relay-proxy"   = "LaunchDarkly Relay Proxy mirror"
    "adot-collector"   = "AWS Distro for OpenTelemetry collector"
  }

  secret_specs = {
    audit_hmac_key      = "STC_AUDIT_HMAC_KEY — base64 urlsafe >=16 bytes for audit chain HMAC"
    token_store_key     = "STC_TOKEN_STORE_KEY — base64 urlsafe 32 bytes for AES-GCM"
    ld_sdk_key          = "LaunchDarkly server-side SDK key"
    litellm_api_key     = "LiteLLM master/provider key"
    rds_master_password = "Aurora master password"
    redis_auth_token    = "ElastiCache Redis auth token"
    qdrant_api_key      = "Qdrant REST API key"
    redis_url           = "Fully-formed rediss:// URL composed post-apply"
  }

  # Tags merged into every resource on top of provider default_tags.
  base_tags = {
    name_prefix = local.name_prefix
  }
}
