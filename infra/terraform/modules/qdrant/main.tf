# ECS Fargate service for Qdrant. EFS-backed persistence so collection
# state survives task replacement. Internal NLB target for low-latency
# gRPC + REST from the STC service.

locals {
  port_rest = 6333
  port_grpc = 6334
}

resource "aws_cloudwatch_log_group" "qdrant" {
  name              = "/${var.name_prefix}/qdrant"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${var.name_prefix}-qdrant-logs" }
}

resource "aws_efs_file_system" "qdrant" {
  creation_token   = "${var.name_prefix}-qdrant"
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"
  tags             = { Name = "${var.name_prefix}-qdrant-efs" }
}

resource "aws_efs_mount_target" "qdrant" {
  for_each        = toset(var.subnet_ids)
  file_system_id  = aws_efs_file_system.qdrant.id
  subnet_id       = each.key
  security_groups = [var.security_group_id]
}

resource "aws_ecs_task_definition" "qdrant" {
  family                   = "${var.name_prefix}-qdrant"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arn

  volume {
    name = "qdrant-storage"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.qdrant.id
      transit_encryption = "ENABLED"
    }
  }

  container_definitions = jsonencode([
    {
      name         = "qdrant"
      image        = "${var.ecr_repo_url}:${var.image_tag}"
      essential    = true
      portMappings = [
        { containerPort = local.port_rest, hostPort = local.port_rest, protocol = "tcp" },
        { containerPort = local.port_grpc, hostPort = local.port_grpc, protocol = "tcp" },
      ]
      mountPoints = [
        { sourceVolume = "qdrant-storage", containerPath = "/qdrant/storage", readOnly = false },
      ]
      environment = [
        { name = "QDRANT__SERVICE__HTTP_PORT", value = tostring(local.port_rest) },
        { name = "QDRANT__SERVICE__GRPC_PORT", value = tostring(local.port_grpc) },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.qdrant.name
          awslogs-region        = var.region
          awslogs-stream-prefix = "qdrant"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "wget -qO- http://127.0.0.1:${local.port_rest}/ > /dev/null || exit 1"]
        interval    = 15
        timeout     = 3
        retries     = 3
        startPeriod = 30
      }
    }
  ])

  tags = { Name = "${var.name_prefix}-qdrant" }
}

resource "aws_ecs_service" "qdrant" {
  name            = "${var.name_prefix}-qdrant"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.qdrant.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn = aws_service_discovery_service.qdrant.arn
    port         = local.port_rest
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = { Name = "${var.name_prefix}-qdrant" }
}

resource "aws_service_discovery_private_dns_namespace" "this" {
  count       = var.create_namespace ? 1 : 0
  name        = var.namespace
  vpc         = var.vpc_id
  description = "STC internal service discovery"
  tags        = { Name = "${var.name_prefix}-svcdisc" }
}

data "aws_service_discovery_dns_namespace" "existing" {
  count = var.create_namespace ? 0 : 1
  name  = var.namespace
  type  = "DNS_PRIVATE"
}

locals {
  namespace_id = var.create_namespace ? aws_service_discovery_private_dns_namespace.this[0].id : data.aws_service_discovery_dns_namespace.existing[0].id
}

resource "aws_service_discovery_service" "qdrant" {
  name = "qdrant"

  dns_config {
    namespace_id = local.namespace_id
    dns_records {
      ttl  = 10
      type = "A"
    }
    routing_policy = "MULTIVALUE"
  }

  health_check_custom_config {
    failure_threshold = 1
  }

  tags = { Name = "${var.name_prefix}-qdrant-svcdisc" }
}
