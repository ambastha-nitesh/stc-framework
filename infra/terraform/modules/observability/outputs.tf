output "amp_workspace_id" { value = aws_prometheus_workspace.this.id }
output "amp_workspace_arn" { value = aws_prometheus_workspace.this.arn }
output "amp_remote_write_endpoint" {
  value = "${aws_prometheus_workspace.this.prometheus_endpoint}api/v1/remote_write"
}
output "alarm_names" {
  value = [for a in aws_cloudwatch_metric_alarm.this : a.alarm_name]
}
