# IAM roles for:
#   - GitHub Actions (OIDC) — lets CI assume a deploy role without
#     long-lived AWS keys.
#   - ECS task_execution — pulls images from ECR, writes logs, reads
#     secrets at task start.
#   - ECS task_role — what the RUNNING task can do (write audit to S3,
#     push metrics to AMP, reach Secrets Manager at runtime).
#
# The OIDC provider is guarded so only one workspace per account
# manages it — subsequent workspaces reference it as data.

data "aws_caller_identity" "this" {}

# --- GitHub OIDC provider (optional) ----------------------------------

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.manage_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
  tags            = { Name = "${var.name_prefix}-github-oidc" }
}

data "aws_iam_openid_connect_provider" "github_existing" {
  count = var.manage_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  oidc_provider_arn = var.manage_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github_existing[0].arn
}

# --- GitHub deploy role ------------------------------------------------

data "aws_iam_policy_document" "github_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = var.github_subject_patterns
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${var.name_prefix}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_trust.json
  tags               = { Name = "${var.name_prefix}-github-deploy" }
}

# Scoped deploy permissions: ECR push, ECS update-service, Secrets
# Manager read for the env's secrets only, IAM PassRole for the task
# roles, Terraform state bucket access.
data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid = "EcrPush"
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeRepositories",
      "ecr:DescribeImages",
    ]
    resources = ["*"]
  }

  statement {
    sid = "EcsUpdate"
    actions = [
      "ecs:UpdateService",
      "ecs:DescribeServices",
      "ecs:RegisterTaskDefinition",
      "ecs:DescribeTaskDefinition",
      "ecs:ListTasks",
      "ecs:DescribeTasks",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "PassExecAndTaskRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.task_execution.arn, aws_iam_role.task.arn]
  }

  statement {
    sid = "SecretsRead"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = var.secret_arns
  }

  statement {
    sid       = "CloudWatchLogsRead"
    actions   = ["logs:DescribeLogGroups", "logs:DescribeLogStreams"]
    resources = ["*"]
  }

  statement {
    sid     = "TfStateBucket"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${var.tfstate_bucket}",
      "arn:aws:s3:::${var.tfstate_bucket}/*",
    ]
  }

  statement {
    sid       = "TfStateLock"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:DeleteItem"]
    resources = [var.tfstate_lock_arn]
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "${var.name_prefix}-github-deploy"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}

# --- ECS task execution role ------------------------------------------

data "aws_iam_policy_document" "ecs_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    effect  = "Allow"
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "${var.name_prefix}-task-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_trust.json
  tags               = { Name = "${var.name_prefix}-task-exec" }
}

resource "aws_iam_role_policy_attachment" "task_execution_aws_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "task_execution_extras" {
  statement {
    sid = "SecretsFetchAtStart"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = var.secret_arns
  }

  statement {
    sid       = "KmsDecryptForSecrets"
    actions   = ["kms:Decrypt", "kms:DescribeKey"]
    resources = var.kms_key_arns
  }
}

resource "aws_iam_role_policy" "task_execution_extras" {
  name   = "${var.name_prefix}-task-exec-extras"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.task_execution_extras.json
}

# --- ECS task role (application-level permissions) --------------------

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_trust.json
  tags               = { Name = "${var.name_prefix}-task" }
}

data "aws_iam_policy_document" "task_runtime" {
  statement {
    sid = "AuditBucketPut"
    actions = [
      "s3:PutObject",
      "s3:PutObjectAcl",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:PutObjectRetention",
      "s3:PutObjectLegalHold",
    ]
    resources = [
      var.s3_audit_bucket_arn,
      "${var.s3_audit_bucket_arn}/*",
    ]
  }

  statement {
    sid       = "KmsForAuditBucket"
    actions   = ["kms:GenerateDataKey", "kms:Decrypt", "kms:Encrypt"]
    resources = var.kms_key_arns
  }

  statement {
    sid = "AmpRemoteWrite"
    actions = [
      "aps:RemoteWrite",
      "aps:QueryMetrics",
      "aps:GetSeries",
      "aps:GetLabels",
      "aps:GetMetricMetadata",
    ]
    resources = var.amp_workspace_arns
  }

  statement {
    sid = "CloudWatchLogsPut"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogStreams",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "SecretsRuntimeRead"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.secret_arns
  }
}

resource "aws_iam_role_policy" "task_runtime" {
  name   = "${var.name_prefix}-task-runtime"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task_runtime.json
}
