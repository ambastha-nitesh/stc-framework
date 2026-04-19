# Root-stack backend. Keyed by workspace so ``dev`` / ``staging`` /
# ``prod`` each get their own state object. Bucket + DynamoDB table
# are provisioned by ``infra/terraform/bootstrap`` (run once per
# account).
#
# Values must match the bootstrap outputs. Override via
# ``terraform init -backend-config=key=value`` if you mirror state to
# a different region/account.

terraform {
  backend "s3" {
    bucket         = "stc-framework-tfstate"   # replaced via -backend-config
    key            = "stc-framework/${terraform.workspace}/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "stc-framework-tfstate-lock"
    encrypt        = true
  }
}
