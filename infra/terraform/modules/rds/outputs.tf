output "cluster_identifier" { value = aws_rds_cluster.this.cluster_identifier }
output "cluster_endpoint" { value = aws_rds_cluster.this.endpoint }
output "cluster_reader_endpoint" { value = aws_rds_cluster.this.reader_endpoint }
output "cluster_arn" { value = aws_rds_cluster.this.arn }
output "port" { value = aws_rds_cluster.this.port }
output "database_name" { value = aws_rds_cluster.this.database_name }
output "master_username" { value = aws_rds_cluster.this.master_username }

# ``manage_master_user_password = true`` makes RDS publish the generated
# password as a Secrets Manager secret. The ARN is nested under
# ``master_user_secret``; downstream consumers reference via try().
output "master_user_secret_arn" {
  value       = try(aws_rds_cluster.this.master_user_secret[0].secret_arn, "")
  description = "Secrets Manager ARN holding the RDS master credentials (JSON with username + password)."
}
