# Secrets Manager entries. Terraform creates the secret + an empty
# initial version; real plaintext values are set out-of-band via
# ``aws secretsmanager put-secret-value`` (documented in the deployment
# runbook). This keeps secrets out of state files and tfvars.

resource "aws_secretsmanager_secret" "this" {
  for_each    = var.specs
  name        = "${var.name_prefix}-${each.key}"
  description = each.value
  kms_key_id  = var.kms_key_arn

  # Allow recovery for 7 days in case of accidental delete in dev; prod
  # should set higher. Aurora + ElastiCache hold references to password
  # secrets so accidental deletion would otherwise brick them.
  recovery_window_in_days = var.recovery_window_days

  tags = { Name = "${var.name_prefix}-secret-${each.key}", purpose = each.value }
}

# Placeholder initial version. Operators overwrite via CLI/runbook;
# ``lifecycle.ignore_changes`` prevents Terraform from clobbering the
# real value on subsequent applies.
resource "aws_secretsmanager_secret_version" "placeholder" {
  for_each      = aws_secretsmanager_secret.this
  secret_id     = each.value.id
  secret_string = "__uninitialised__"
  lifecycle {
    ignore_changes = [secret_string, version_stages]
  }
}
