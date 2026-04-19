output "cluster_endpoint" { value = aws_rds_cluster.this.endpoint }
output "cluster_reader_endpoint" { value = aws_rds_cluster.this.reader_endpoint }
output "cluster_arn" { value = aws_rds_cluster.this.arn }
output "port" { value = aws_rds_cluster.this.port }
output "database_name" { value = aws_rds_cluster.this.database_name }
output "master_username" { value = aws_rds_cluster.this.master_username }
