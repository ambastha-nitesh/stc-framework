# ECS Fargate service for the LaunchDarkly Relay Proxy. Sits between
# the STC service and LD SaaS: caches flag state, reduces outbound
# egress, and absorbs LD API outages. Exposed via Cloud Map so the
# STC container references ``http://ld-relay.<namespace>:8030``.

locals {
  relay_port = 8030
}

resource "aws_cloudwatch_log_group" "relay" {
  name              = "/${var.name_prefix}/ld-relay"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${var.name_prefix}-ld-relay-logs" }
}

resource "aws_ecs_task_definition" "relay" {
  family                   = "${var.name_prefix}-ld-relay"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "ld-relay"
      image     = "${var.ecr_repo_url}:${var.image_tag}"
      essential = true
      portMappings = [
        { containerPort = local.relay_port, hostPort = local.relay_port, protocol = "tcp" },
      ]
      environment = [
        # Relay reads the key from env; Terraform sources it via the
        # ECS ``secrets`` block below so the plaintext never hits state.
        { name = "HEALTHCHECK__PORT", value = tostring(local.relay_port) },
      ]
      secrets = [
        { name = "LD_ENV_default", valueFrom = var.ld_sdk_key_secret_arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.relay.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "ld-relay"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "wget -qO- http://127.0.0.1:${local.relay_port}/status > /dev/null || exit 1"]
        interval    = 15
        timeout     = 3
        retries     = 3
        startPeriod = 30
      }
    }
  ])

  tags = { Name = "${var.name_prefix}-ld-relay" }
}

resource "aws_ecs_service" "relay" {
  name            = "${var.name_prefix}-ld-relay"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.relay.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.relay.arn
    port         = local.relay_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = { Name = "${var.name_prefix}-ld-relay" }
}

resource "aws_service_discovery_service" "relay" {
  name = "ld-relay"

  dns_config {
    namespace_id = var.namespace_id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = { Name = "${var.name_prefix}-ld-relay-svcdisc" }
}
