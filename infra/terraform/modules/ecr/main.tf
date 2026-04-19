# ECR repositories for every image the deployment pulls: STC service,
# LaunchDarkly Relay Proxy mirror, and the ADOT collector mirror. All
# use KMS-encrypted storage and scan-on-push.

resource "aws_ecr_repository" "this" {
  for_each             = var.repos
  name                 = "${var.name_prefix}-${each.key}"
  image_tag_mutability = var.image_tag_mutability

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.kms_key_arn
  }

  tags = { Name = "${var.name_prefix}-${each.key}", purpose = each.value }
}

# Keep the newest 30 tagged images, expire untagged after 7 days.
resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the 30 most recent tagged images."
        selection = {
          tagStatus     = "tagged"
          tagPatternList = ["*"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Expire untagged images after 7 days."
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
    ]
  })
}
