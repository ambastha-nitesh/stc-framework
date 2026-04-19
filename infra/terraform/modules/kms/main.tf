# Customer-managed KMS keys — one per purpose so a policy that grants
# access to, say, audit bucket decryption does not incidentally allow
# RDS storage decryption. Keys rotate annually by default.

resource "aws_kms_key" "this" {
  for_each                = var.purposes
  description             = each.value
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = { Name = "${var.name_prefix}-kms-${each.key}", purpose = each.key }
}

resource "aws_kms_alias" "this" {
  for_each      = var.purposes
  name          = "alias/${var.name_prefix}-${each.key}"
  target_key_id = aws_kms_key.this[each.key].key_id
}
