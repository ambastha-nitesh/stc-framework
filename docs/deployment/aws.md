# AWS deployment runbook

End-to-end runbook for standing up the STC Framework on AWS via the
Terraform stack in `infra/terraform/` and the GitHub Actions workflow
in `.github/workflows/deploy.yml`. Follow the phases in order; each
has its own verification step.

## Architecture

```
Internet
   │ TLS (ACM)
   ▼
API Gateway HTTP API ── optional WAFv2 ──┐
   │ VPC Link                             │
   ▼                                      │
Internal ALB :80                          │
   │ HTTP                                 │
   ▼                                      │
ECS Fargate service (STC framework) ──► Cloud Map ──► LD Relay (ECS)
   │ 4 containers: stc, adot, presidio?, audit-sync
   ├──► Qdrant (ECS) via Cloud Map
   ├──► ElastiCache Redis (TLS)
   ├──► Aurora Postgres (IAM auth)
   ├──► S3 Object Lock (audit)
   ├──► AMP workspace (metrics via ADOT)
   └──► CloudWatch Logs
```

## Prerequisites

- AWS account with administrator access for the initial bootstrap.
- `aws` CLI v2, `terraform` >= 1.6 < 2.0, `docker` (optional for local smokes).
- Route 53 hosted zone (only when `api_domain_name` is set).
- SNS topic for alarm notifications (staging/prod).
- LaunchDarkly workspace with a server-side SDK key.

## Phase 0 — bootstrap the state backend

One-off per AWS account + region. Creates the S3 bucket, DynamoDB
lock table, and KMS key used by every other `terraform init`.

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply -auto-approve
# Note the outputs — especially state_bucket — for phase 1.
```

## Phase 1 — initialise the root stack

```bash
cd ../                                    # into infra/terraform/
terraform init \
  -backend-config="bucket=$(terraform -chdir=bootstrap output -raw state_bucket)" \
  -backend-config="dynamodb_table=$(terraform -chdir=bootstrap output -raw state_table)"
terraform workspace new dev               # or: staging / prod
```

## Phase 2 — seed secrets

Terraform creates the Secrets Manager entries with placeholder values.
Real plaintext must be set out-of-band so secrets never enter tfstate.

```bash
NP=stc-framework-dev
# 32-byte HMAC key for audit chain integrity
aws secretsmanager put-secret-value --secret-id ${NP}-audit_hmac_key \
  --secret-string "$(openssl rand -base64 32)"
# 32-byte AES-GCM key for the token store
aws secretsmanager put-secret-value --secret-id ${NP}-token_store_key \
  --secret-string "$(openssl rand -base64 32)"
# LaunchDarkly server-side SDK key
aws secretsmanager put-secret-value --secret-id ${NP}-ld_sdk_key \
  --secret-string "sdk-<server-side-key-from-LD-dashboard>"
# LiteLLM / provider keys
aws secretsmanager put-secret-value --secret-id ${NP}-litellm_api_key \
  --secret-string "sk-..."
# Aurora master password (seed once; Terraform reads via data source)
aws secretsmanager put-secret-value --secret-id ${NP}-rds_master_password \
  --secret-string "$(openssl rand -base64 24)"
# ElastiCache auth token
aws secretsmanager put-secret-value --secret-id ${NP}-redis_auth_token \
  --secret-string "$(openssl rand -hex 32)"
```

After Redis + RDS are created, assemble the composite connection
strings into the remaining secrets:

```bash
redis_ep=$(terraform output -raw redis_primary_endpoint)
redis_token=$(aws secretsmanager get-secret-value --secret-id ${NP}-redis_auth_token --query SecretString --output text)
aws secretsmanager put-secret-value --secret-id ${NP}-redis_url \
  --secret-string "rediss://:${redis_token}@${redis_ep}:6379/0"
```

## Phase 3 — apply the stack

```bash
terraform apply \
  -var-file=environments/dev/terraform.tfvars \
  -var="image_tag=main-latest"
```

Expect ~15 minutes on first apply (Aurora is the bottleneck). Outputs:
`api_endpoint`, `audit_bucket_name`, `redis_primary_endpoint`,
`github_deploy_role_arn`.

## Phase 4 — build + push the first image

Terraform cannot boot the service until an image exists at the
referenced tag. Two options:

1. **Manual** — one-off:
   ```bash
   aws ecr get-login-password | docker login --username AWS --password-stdin \
     $(terraform output -json ecr_repositories | jq -r '."stc-framework"')
   docker build --build-arg DEPLOYED_SUBSYSTEMS=service,litellm,redis,launchdarkly,otlp \
                --build-arg GIT_SHA=$(git rev-parse HEAD) \
                -t $(terraform output -json ecr_repositories | jq -r '."stc-framework"'):main-latest .
   docker push $(terraform output -json ecr_repositories | jq -r '."stc-framework"'):main-latest
   ```

2. **CI-driven** — merge to main once the `github_deploy_role_arn`
   from Terraform is plugged into `.github/deploy-matrix.yaml`.

## Phase 5 — verify

```bash
curl -sfI $(terraform output -raw api_endpoint)/healthz
curl -sf   $(terraform output -raw api_endpoint)/readyz | jq
curl -sf -X POST $(terraform output -raw api_endpoint)/v1/query \
     -H "content-type: application/json" \
     -d '{"query":"hello","tenant_id":"smoke"}' | jq
```

Prometheus scrape works via the ADOT sidecar; open the AMP console and
query `sum(rate(stc_queries_total[5m]))`.

## Rotating secrets

Every `aws secretsmanager put-secret-value ...` + `aws ecs update-service
--force-new-deployment` picks up the new value via ECS task secrets[].
Terraform is unaffected (the placeholder version is `ignore_changes`).

## Tearing down a dev environment

```bash
terraform destroy -var-file=environments/dev/terraform.tfvars
# Optionally delete the CMKs + secrets manually (AWS keeps them for 30 days by default).
```

## Disaster recovery

- **Aurora snapshot restore**: backup retention defaults to 14 days in
  prod. `aws rds restore-db-cluster-from-snapshot` then re-point the
  Terraform state via `terraform import`.
- **Redis re-provision**: ElastiCache state is ephemeral; redeploy by
  `terraform apply` + re-seed budget counters (zero is a safe default).
- **Audit bucket**: Object Lock COMPLIANCE mode means records cannot
  be deleted before their retention date even by the account root.
  Accidental `terraform destroy` is blocked by `deletion_protection`
  in prod tfvars.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Service task cycles "unable to pull image" | Image tag not pushed to ECR | Run phase 4 or let CI push. |
| `/readyz` returns 503 | A downstream adapter is unhealthy. See JSON body for `unhealthy` adapter list. | Check its security group + Secrets Manager seed value. |
| Terraform drift on `secret_version` | Placeholder value was overwritten by CLI; Terraform wants to reset it. | `terraform state rm module.secrets.aws_secretsmanager_secret_version.placeholder[...]` |
| LD flag evaluation always returns defaults | Relay Proxy is unreachable or its SDK key secret is wrong. | Check `stc_feature_flag_fallback_total` in AMP + relay logs in CW. |
