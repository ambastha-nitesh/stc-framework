output "service_name" { value = aws_ecs_service.relay.name }
output "port" { value = local.relay_port }
output "relay_url" {
  value       = "http://ld-relay.${var.namespace_name}:${local.relay_port}"
  description = "Populate STC_LD_RELAY_URL with this value."
}
