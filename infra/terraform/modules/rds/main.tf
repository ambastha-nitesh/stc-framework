# Aurora PostgreSQL Serverless v2. Holds the history + escalation
# stores (sqlalchemy-backed). Min/max ACUs driven by tfvars so dev can
# scale near zero while prod sustains peak throughput.

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-rds"
  subnet_ids = var.subnet_ids
  tags       = { Name = "${var.name_prefix}-rds-subnets" }
}

resource "aws_rds_cluster_parameter_group" "this" {
  name_prefix = "${var.name_prefix}-rds-"
  family      = "aurora-postgresql15"

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  tags = { Name = "${var.name_prefix}-rds-pg" }
}

# Look up the master password at apply time so its plaintext never
# passes through state. Operators seed this via the runbook.
data "aws_secretsmanager_secret_version" "master_password" {
  secret_id = var.master_password_secret_arn
}

resource "aws_rds_cluster" "this" {
  cluster_identifier                  = "${var.name_prefix}-aurora"
  engine                              = "aurora-postgresql"
  engine_mode                         = "provisioned"
  engine_version                      = "15.5"
  database_name                       = var.database_name
  master_username                     = var.master_username
  master_password                     = data.aws_secretsmanager_secret_version.master_password.secret_string
  db_subnet_group_name                = aws_db_subnet_group.this.name
  vpc_security_group_ids              = [var.security_group_id]
  storage_encrypted                   = true
  kms_key_id                          = var.kms_key_arn
  backup_retention_period             = var.backup_retention_days
  deletion_protection                 = var.deletion_protection
  db_cluster_parameter_group_name     = aws_rds_cluster_parameter_group.this.name
  iam_database_authentication_enabled = true

  serverlessv2_scaling_configuration {
    min_capacity = var.min_acu
    max_capacity = var.max_acu
  }

  lifecycle {
    # Master password is rotated out-of-band; ignore drift.
    ignore_changes = [master_password]
  }

  tags = { Name = "${var.name_prefix}-aurora" }
}

resource "aws_rds_cluster_instance" "this" {
  for_each             = toset([for i in range(var.instance_count) : tostring(i)])
  identifier           = "${var.name_prefix}-aurora-${each.key}"
  cluster_identifier   = aws_rds_cluster.this.id
  instance_class       = "db.serverless"
  engine               = aws_rds_cluster.this.engine
  engine_version       = aws_rds_cluster.this.engine_version
  db_subnet_group_name = aws_db_subnet_group.this.name
  tags                 = { Name = "${var.name_prefix}-aurora-${each.key}" }
}
