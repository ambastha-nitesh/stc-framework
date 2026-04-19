output "api_id" { value = aws_apigatewayv2_api.this.id }
output "api_endpoint" {
  value       = aws_apigatewayv2_api.this.api_endpoint
  description = "Default ``execute-api`` endpoint (AWS-provided hostname)."
}
output "stage_arn" { value = aws_apigatewayv2_stage.default.arn }
output "custom_domain_target" {
  value = length(aws_apigatewayv2_domain_name.this) > 0 ? aws_apigatewayv2_domain_name.this[0].domain_name_configuration[0].target_domain_name : ""
  description = "CNAME this to the value of ``custom_domain_target`` when a custom domain is set."
}
