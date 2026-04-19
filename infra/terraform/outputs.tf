output "environment" { value = local.environment }

output "vpc_id" { value = module.network.vpc_id }

output "cluster_name" { value = aws_ecs_cluster.this.name }

output "api_endpoint" { value = module.api_gateway.api_endpoint }
output "api_custom_domain_target" { value = module.api_gateway.custom_domain_target }

output "alb_dns_name" { value = aws_lb.internal.dns_name }

output "ecr_repositories" { value = module.ecr.repository_urls }

output "secret_arns" { value = module.secrets.secret_arns }

output "rds_endpoint" { value = module.rds.cluster_endpoint }
output "rds_reader_endpoint" { value = module.rds.cluster_reader_endpoint }

output "redis_primary_endpoint" { value = module.elasticache.primary_endpoint }

output "audit_bucket_name" { value = module.s3_audit.bucket_name }

output "ld_relay_url" { value = module.ld_relay.relay_url }

output "amp_workspace_id" { value = module.observability.amp_workspace_id }
output "amp_remote_write_endpoint" { value = module.observability.amp_remote_write_endpoint }

output "github_deploy_role_arn" { value = module.iam.github_deploy_role_arn }
