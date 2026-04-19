output "service_name" { value = aws_ecs_service.qdrant.name }
output "dns_name" {
  value       = "qdrant.${var.namespace}"
  description = "Cloud Map DNS name reachable from other tasks in the same VPC."
}
output "namespace_id" { value = local.namespace_id }
output "port" { value = local.port_rest }
