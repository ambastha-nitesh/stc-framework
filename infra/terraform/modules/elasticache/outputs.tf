output "primary_endpoint" { value = aws_elasticache_replication_group.this.primary_endpoint_address }
output "reader_endpoint" { value = aws_elasticache_replication_group.this.reader_endpoint_address }
output "port" { value = aws_elasticache_replication_group.this.port }
output "replication_group_id" { value = aws_elasticache_replication_group.this.replication_group_id }

# Sensitive — only the root module reads this to compose the full
# redis_url secret. It's never emitted to the CI logs because every
# downstream output that uses it is either (a) written straight into
# Secrets Manager or (b) marked sensitive = true.
output "auth_token" {
  value       = random_password.auth_token.result
  sensitive   = true
  description = "Redis auth token value. Consumed by the root module to compose the redis_url secret."
}
