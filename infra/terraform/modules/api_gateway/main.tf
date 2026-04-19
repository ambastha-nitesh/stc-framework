# API Gateway HTTP API in front of the internal ALB. TLS terminates at
# the edge (ACM cert), optional WAFv2 ACL sits between the public IP
# and the API. All traffic reaches the VPC via the VPC Link.

resource "aws_apigatewayv2_api" "this" {
  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"
  description   = "Public entry point for the STC Framework."
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["content-type", "authorization", "x-request-id"]
    max_age       = 3600
  }
  tags = { Name = "${var.name_prefix}-api" }
}

resource "aws_apigatewayv2_vpc_link" "this" {
  name               = "${var.name_prefix}-vpclink"
  subnet_ids         = var.subnet_ids
  security_group_ids = [var.vpc_link_security_group_id]
  tags               = { Name = "${var.name_prefix}-vpclink" }
}

resource "aws_apigatewayv2_integration" "this" {
  api_id             = aws_apigatewayv2_api.this.id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri    = var.alb_listener_arn
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.this.id

  payload_format_version = "1.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.this.id}"
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/${var.name_prefix}/api-gateway"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${var.name_prefix}-apigw-logs" }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId         = "$context.requestId"
      ip                = "$context.identity.sourceIp"
      requestTime       = "$context.requestTime"
      httpMethod        = "$context.httpMethod"
      routeKey          = "$context.routeKey"
      status            = "$context.status"
      protocol          = "$context.protocol"
      responseLength    = "$context.responseLength"
      integrationStatus = "$context.integrationStatus"
      integrationError  = "$context.integrationErrorMessage"
    })
  }

  default_route_settings {
    throttling_burst_limit = var.throttle_burst
    throttling_rate_limit  = var.throttle_rate
    detailed_metrics_enabled = true
  }

  tags = { Name = "${var.name_prefix}-apigw-default" }
}

# --- custom domain (optional) ---------------------------------------

resource "aws_apigatewayv2_domain_name" "this" {
  count       = var.domain_name == "" ? 0 : 1
  domain_name = var.domain_name

  domain_name_configuration {
    certificate_arn = var.acm_certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }

  tags = { Name = var.domain_name }
}

resource "aws_apigatewayv2_api_mapping" "this" {
  count       = var.domain_name == "" ? 0 : 1
  api_id      = aws_apigatewayv2_api.this.id
  domain_name = aws_apigatewayv2_domain_name.this[0].id
  stage       = aws_apigatewayv2_stage.default.id
}

# --- WAFv2 association (optional) -----------------------------------

resource "aws_wafv2_web_acl_association" "this" {
  count        = var.waf_web_acl_arn == "" ? 0 : 1
  resource_arn = aws_apigatewayv2_stage.default.arn
  web_acl_arn  = var.waf_web_acl_arn
}
