output "service_name" { value = aws_ecs_service.this.name }
output "task_definition_arn" { value = aws_ecs_task_definition.this.arn }
output "task_family" { value = aws_ecs_task_definition.this.family }
output "log_group_name" { value = aws_cloudwatch_log_group.main.name }
