# AMP workspace + CloudWatch alarms. The ADOT sidecar in the service
# task writes to the AMP workspace via the task role's ``aps:RemoteWrite``
# permission. Alarms reference CloudWatch metrics (from the ALB + ECS)
# and AMP metrics via CW metric mathhoist (``aws_cloudwatch_metric_alarm``
# cannot query AMP directly; use CloudWatch Container Insights +
# custom exporters for that story).

resource "aws_prometheus_workspace" "this" {
  alias = "${var.name_prefix}-amp"
  tags  = { Name = "${var.name_prefix}-amp" }
}

locals {
  # Alarm definitions. ``for_each`` means adding a new alarm is a
  # one-liner in this map, no copy-paste.
  alarms = {
    alb_5xx_high = {
      description = "ALB 5xx rate > 0 sustained for 5 minutes."
      metric_name = "HTTPCode_ELB_5XX_Count"
      namespace   = "AWS/ApplicationELB"
      statistic   = "Sum"
      threshold   = 1
      period      = 60
      eval_periods = 5
      comparison  = "GreaterThanOrEqualToThreshold"
      dimensions  = { LoadBalancer = var.alb_dimension }
    }
    target_5xx_high = {
      description = "ALB target 5xx rate > 0 sustained for 5 minutes."
      metric_name = "HTTPCode_Target_5XX_Count"
      namespace   = "AWS/ApplicationELB"
      statistic   = "Sum"
      threshold   = 1
      period      = 60
      eval_periods = 5
      comparison  = "GreaterThanOrEqualToThreshold"
      dimensions  = { LoadBalancer = var.alb_dimension }
    }
    ecs_running_count_low = {
      description = "ECS running count dropped below the minimum."
      metric_name = "RunningTaskCount"
      namespace   = "ECS/ContainerInsights"
      statistic   = "Minimum"
      threshold   = var.min_running_tasks
      period      = 60
      eval_periods = 3
      comparison  = "LessThanThreshold"
      dimensions = {
        ClusterName = var.ecs_cluster_name
        ServiceName = var.ecs_service_name
      }
    }
    rds_cpu_high = {
      description = "Aurora CPU > 80% for 10 min."
      metric_name = "CPUUtilization"
      namespace   = "AWS/RDS"
      statistic   = "Average"
      threshold   = 80
      period      = 60
      eval_periods = 10
      comparison  = "GreaterThanThreshold"
      dimensions  = { DBClusterIdentifier = var.rds_cluster_identifier }
    }
    redis_cpu_high = {
      description = "Redis CPU > 75% for 10 min."
      metric_name = "EngineCPUUtilization"
      namespace   = "AWS/ElastiCache"
      statistic   = "Average"
      threshold   = 75
      period      = 60
      eval_periods = 10
      comparison  = "GreaterThanThreshold"
      dimensions  = { ReplicationGroupId = var.redis_replication_group_id }
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each            = local.alarms
  alarm_name          = "${var.name_prefix}-${each.key}"
  alarm_description   = each.value.description
  metric_name         = each.value.metric_name
  namespace           = each.value.namespace
  statistic           = each.value.statistic
  period              = each.value.period
  threshold           = each.value.threshold
  evaluation_periods  = each.value.eval_periods
  comparison_operator = each.value.comparison
  dimensions          = each.value.dimensions
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.sns_topic_arn == "" ? [] : [var.sns_topic_arn]
  ok_actions          = var.sns_topic_arn == "" ? [] : [var.sns_topic_arn]
  tags                = { Name = "${var.name_prefix}-${each.key}" }
}
