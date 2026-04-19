output "secret_arns" {
  value = { for k, v in aws_secretsmanager_secret.this : k => v.arn }
}

output "secret_names" {
  value = { for k, v in aws_secretsmanager_secret.this : k => v.name }
}

output "all_secret_arns" {
  value = [for v in aws_secretsmanager_secret.this : v.arn]
}
