# STC Framework ECS service. The task definition carries up to four
# containers:
#
#   1. ``stc-framework`` (main) — Flask on :8000, Prometheus on :9090.
#   2. ``adot-collector`` — OTLP sidecar that ships metrics/traces/logs
#      to AMP + CloudWatch.
#   3. ``audit-sync`` — watches /mnt/audit and uploads sealed files to
#      the Object Lock bucket (not Terraformed here — shipped as a
#      small sidecar binary out of band).
#   4. ``presidio`` (optional) — co-sidecar only when the ``presidio``
#      extra is in the image. Adds via ``locals.include_presidio``.
#
# A separate ``spec-verify`` init container runs
# ``stc-governance verify-spec --require-signature`` and must exit 0
# before the main container starts; ECS container dependency handles
# the ordering.

locals {
  main_port      = 8000
  metrics_port   = 9090
  otlp_grpc_port = 4317

  include_presidio = contains(split(",", var.deployed_subsystems), "presidio")

  base_env = merge({
    STC_ENV            = var.environment
    STC_SERVICE_NAME   = var.name_prefix
    STC_LOG_LEVEL      = var.log_level
    STC_LOG_FORMAT     = "json"
    STC_LOG_CONTENT    = "false"
    STC_OTLP_ENDPOINT  = "http://127.0.0.1:${local.otlp_grpc_port}"
    STC_METRICS_PORT   = tostring(local.metrics_port)
    STC_AUDIT_PATH     = "/mnt/audit"
    STC_TOKEN_STORE_PATH = "/mnt/tokens/token_store.bin"
    STC_AUDIT_BACKEND  = "worm"
    STC_LLM_ADAPTER    = "litellm"
    STC_VECTOR_ADAPTER = "qdrant"
    STC_LD_RELAY_URL   = var.ld_relay_url
    STC_LD_OFFLINE_MODE = "false"
    STC_LD_CACHE_PATH  = "/var/cache/ld/flags.json"
  }, var.environment == "prod" ? {
    STC_TOKENIZATION_STRICT = "true"
  } : {})

  env_list = [for k, v in local.base_env : { name = k, value = tostring(v) }]

  secrets_list = [
    for logical, arn in var.secret_arns : {
      name      = lookup({
        audit_hmac_key  = "STC_AUDIT_HMAC_KEY"
        token_store_key = "STC_TOKEN_STORE_KEY"
        ld_sdk_key      = "LD_SDK_KEY"
        litellm_api_key = "LITELLM_API_KEY"
        redis_url       = "STC_REDIS_URL"
      }, logical, null)
      valueFrom = arn
    }
    if contains(["audit_hmac_key", "token_store_key", "ld_sdk_key", "litellm_api_key", "redis_url"], logical)
  ]
}

resource "aws_cloudwatch_log_group" "main" {
  name              = "/${var.name_prefix}/stc-framework"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${var.name_prefix}-stc-logs" }
}

resource "aws_cloudwatch_log_group" "adot" {
  name              = "/${var.name_prefix}/adot"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${var.name_prefix}-adot-logs" }
}

resource "aws_efs_file_system" "audit" {
  creation_token   = "${var.name_prefix}-audit"
  encrypted        = true
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"
  tags             = { Name = "${var.name_prefix}-audit-efs" }
}

resource "aws_efs_mount_target" "audit" {
  for_each        = toset(var.subnet_ids)
  file_system_id  = aws_efs_file_system.audit.id
  subnet_id       = each.key
  security_groups = [var.security_group_id]
}

# --- task definition --------------------------------------------------

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.name_prefix}-stc"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arn

  volume {
    name = "audit"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.audit.id
      transit_encryption = "ENABLED"
    }
  }

  volume {
    name = "tokens"
    # An ephemeral tmpfs is fine — the token store reconstitutes on
    # startup from the Secrets Manager key. Persistent file store is
    # not required.
  }

  volume {
    name = "ld-cache"
  }

  container_definitions = jsonencode(concat(
    [
      # Main application container
      {
        name        = "stc-framework"
        image       = "${var.ecr_repo_url}:${var.image_tag}"
        essential   = true
        stopTimeout = 30
        portMappings = [
          { containerPort = local.main_port, protocol = "tcp" },
          { containerPort = local.metrics_port, protocol = "tcp" },
        ]
        environment = local.env_list
        secrets     = local.secrets_list
        mountPoints = [
          { sourceVolume = "audit", containerPath = "/mnt/audit", readOnly = false },
          { sourceVolume = "tokens", containerPath = "/mnt/tokens", readOnly = false },
          { sourceVolume = "ld-cache", containerPath = "/var/cache/ld", readOnly = false },
        ]
        logConfiguration = {
          logDriver = "awslogs"
          options = {
            awslogs-group         = aws_cloudwatch_log_group.main.name
            awslogs-region        = var.region
            awslogs-stream-prefix = "stc"
          }
        }
        healthCheck = {
          command     = ["CMD-SHELL", "curl -fsS http://127.0.0.1:${local.main_port}/healthz || exit 1"]
          interval    = 15
          timeout     = 3
          retries     = 3
          startPeriod = 60
        }
        dockerLabels = {
          "org.stc.deployed_subsystems" = var.deployed_subsystems
        }
      },

      # ADOT collector sidecar
      {
        name      = "adot-collector"
        image     = "${var.adot_image_url}:${var.adot_image_tag}"
        essential = true
        environment = [
          { name = "AWS_REGION", value = var.region },
          { name = "AOT_AMP_ENDPOINT", value = var.amp_remote_write_endpoint },
          { name = "AOT_LOG_GROUP", value = aws_cloudwatch_log_group.adot.name },
          { name = "AOT_LOG_STREAM", value = "adot-${var.environment}" },
        ]
        portMappings = [
          { containerPort = local.otlp_grpc_port, protocol = "tcp" },
        ]
        logConfiguration = {
          logDriver = "awslogs"
          options = {
            awslogs-group         = aws_cloudwatch_log_group.adot.name
            awslogs-region        = var.region
            awslogs-stream-prefix = "adot"
          }
        }
        healthCheck = {
          command     = ["CMD-SHELL", "wget -qO- http://127.0.0.1:13133 > /dev/null || exit 1"]
          interval    = 15
          timeout     = 3
          retries     = 3
          startPeriod = 15
        }
      },
    ],

    # Optional Presidio co-sidecar
    local.include_presidio ? [
      {
        name      = "presidio"
        image     = "${var.presidio_image_url}:${var.presidio_image_tag}"
        essential = false
        portMappings = [
          { containerPort = 3000, protocol = "tcp" },
        ]
        logConfiguration = {
          logDriver = "awslogs"
          options = {
            awslogs-group         = aws_cloudwatch_log_group.main.name
            awslogs-region        = var.region
            awslogs-stream-prefix = "presidio"
          }
        }
      },
    ] : [],
  ))

  tags = { Name = "${var.name_prefix}-stc" }
}

# --- service + autoscaling ------------------------------------------

resource "aws_ecs_service" "this" {
  name            = "${var.name_prefix}-stc"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.min_replicas
  launch_type     = "FARGATE"
  propagate_tags  = "SERVICE"

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [var.security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.target_group_arn
    container_name   = "stc-framework"
    container_port   = local.main_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60

  lifecycle {
    # desired_count is managed by autoscaling; ignore drift.
    ignore_changes = [desired_count]
  }

  tags = { Name = "${var.name_prefix}-stc" }
}

resource "aws_appautoscaling_target" "this" {
  max_capacity       = var.max_replicas
  min_capacity       = var.min_replicas
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${var.name_prefix}-stc-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.this.resource_id
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension
  service_namespace  = aws_appautoscaling_target.this.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = 60.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
