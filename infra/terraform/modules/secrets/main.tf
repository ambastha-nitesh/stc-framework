# Secrets Manager entries. Some secrets are seeded out-of-band via
# ``aws secretsmanager put-secret-value`` (documented in the runbook);
# others are populated by Terraform elsewhere (the elasticache module
# writes the auth token; the root module composes redis_url). The
# caller lists the latter in ``terraform_managed_names`` so this
# module skips the placeholder version for them — otherwise two
# ``aws_secretsmanager_secret_version`` resources would fight over
# the AWSCURRENT stage.

resource "aws_secretsmanager_secret" "this" {
  for_each    = var.specs
  name        = "${var.name_prefix}-${each.key}"
  description = each.value
  kms_key_id  = var.kms_key_arn

  # Aurora + ElastiCache reference these secrets; keep a recovery
  # window so an accidental delete can be un-done.
  recovery_window_in_days = var.recovery_window_days

  tags = { Name = "${var.name_prefix}-secret-${each.key}", purpose = each.value }
}

locals {
  # Secrets that should get a Terraform-written placeholder (the
  # human-seeded ones). Secrets listed in ``terraform_managed_names``
  # are written by another resource and must NOT have a placeholder.
  placeholder_specs = {
    for k, v in var.specs : k => v
    if !contains(var.terraform_managed_names, k)
  }
}

resource "aws_secretsmanager_secret_version" "placeholder" {
  for_each      = local.placeholder_specs
  secret_id     = aws_secretsmanager_secret.this[each.key].id
  secret_string = "__uninitialised__"
  lifecycle {
    ignore_changes = [secret_string, version_stages]
  }
}
