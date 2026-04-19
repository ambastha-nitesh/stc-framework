# Root-stack backend. Keyed by workspace so ``dev`` / ``staging`` /
# ``prod`` each get their own state object. Bucket + DynamoDB table
# are provisioned by ``infra/terraform/bootstrap`` (run once per
# account).
#
# Backend blocks forbid variable interpolation, so bucket / region /
# dynamodb_table MUST be passed via ``terraform init -backend-config``.
# ``workspace_key_prefix`` combined with the default ``key`` gives us
# per-workspace state layout:
#
#     s3://<bucket>/<prefix>/<workspace>/terraform.tfstate
#
# Humans run:
#
#     terraform init \
#       -backend-config="bucket=$(terraform -chdir=bootstrap output -raw state_bucket)" \
#       -backend-config="dynamodb_table=$(terraform -chdir=bootstrap output -raw state_table)" \
#       -backend-config="region=us-east-1"
#
# CI (see .github/workflows/deploy.yml) passes these via the
# ``backend-config`` init step.

terraform {
  backend "s3" {
    key                  = "terraform.tfstate"
    workspace_key_prefix = "stc-framework"
    encrypt              = true
  }
}
