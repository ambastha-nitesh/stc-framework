output "service_name" { value = aws_ecs_service.relay.name }
output "port" { value = local.relay_port }
output "relay_url" {
  value       = "http://ld-relay.${split(".", var.namespace_id)[0]}.stc.internal:${local.relay_port}"
  description = "Populate STC_LD_RELAY_URL with this value."
}
