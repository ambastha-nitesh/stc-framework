# ElastiCache Redis replication group. Backs the Redis-side of the
# KeyValueStore Protocol implemented in
# ``stc_framework/infrastructure/redis_store.py``. TLS in transit and
# at rest are non-negotiable; auth token via Secrets Manager.

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-redis"
  subnet_ids = var.subnet_ids
  tags       = { Name = "${var.name_prefix}-redis-subnets" }
}

resource "aws_elasticache_parameter_group" "this" {
  name        = "${var.name_prefix}-redis"
  family      = "redis7"
  description = "STC Redis parameters — enable keyspace notifications for TTL visibility."

  parameter {
    name  = "notify-keyspace-events"
    value = "AKE"
  }
}

# Generate the auth token with ``random_password`` so Terraform is the
# source of truth from the first apply. The secret_version below then
# distributes the token to the task role via Secrets Manager. This
# replaces the earlier pattern where Terraform read a placeholder value
# from Secrets Manager on first apply and the runbook overwrote the
# secret later — leaving ElastiCache stuck on the placeholder token.
resource "random_password" "auth_token" {
  length      = 40
  special     = false
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
}

resource "aws_secretsmanager_secret_version" "auth_token" {
  secret_id     = var.auth_token_secret_arn
  secret_string = random_password.auth_token.result
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id       = "${var.name_prefix}-redis"
  description                = "STC Framework Redis (${var.name_prefix})."
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = var.node_type
  num_cache_clusters         = var.num_replicas + 1 # primary + replicas
  port                       = 6379
  parameter_group_name       = aws_elasticache_parameter_group.this.name
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [var.security_group_id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = var.kms_key_arn
  auth_token                 = random_password.auth_token.result

  automatic_failover_enabled = var.num_replicas > 0
  multi_az_enabled           = var.num_replicas > 0
  snapshot_retention_limit   = var.snapshot_retention_days

  lifecycle {
    # Token rotation is a deliberate ``modify-replication-group
    # --auth-token-update-strategy ROTATE`` operation, not drift.
    ignore_changes = [auth_token]
  }

  tags = { Name = "${var.name_prefix}-redis" }
}
