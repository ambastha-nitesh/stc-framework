# Terraform — STC Framework AWS stack

Hierarchical Terraform layout. One root module, twelve child modules,
three workspaces (`dev`, `staging`, `prod`). Every module is scoped
tightly: it owns one concern and exposes only what downstream modules
need.

## Layout

```
infra/terraform/
  bootstrap/           # One-shot: S3 + DynamoDB state backend.
  environments/        # Per-env tfvars.
  modules/
    network/           # VPC, subnets, NAT, endpoints, SGs.
    ecr/               # 3 repositories.
    kms/               # 4 CMKs, 1 per purpose.
    iam/               # GitHub OIDC + task roles.
    secrets/           # Secrets Manager entries (placeholders).
    s3_audit/          # Object Lock WORM bucket.
    rds/               # Aurora Postgres Serverless v2.
    elasticache/       # Redis 7.1 replication group.
    qdrant/            # Fargate + EFS + Cloud Map.
    ld_relay/          # Fargate + Cloud Map.
    service/           # Fargate + autoscaling + EFS + task def.
    api_gateway/       # HTTP API + VPC Link + WAF assoc.
    observability/     # AMP workspace + CW alarms.
```

## Workspaces

- `dev` — single-NAT, 1 replica, short audit retention, deletion
  protection off, mutable ECR tags. Cheap to tear down.
- `staging` — multi-AZ, 2 replicas, 1-year audit retention, deletion
  protection on. Mirrors prod topology at smaller scale.
- `prod` — 3 AZ, 3-10 replicas, 6-year audit retention (SEC 17a-4 /
  FINRA 4511), immutable ECR tags, multi-AZ Redis, larger RDS.

## Bootstrap

```bash
cd bootstrap
terraform init && terraform apply
```

Outputs `state_bucket` + `state_table`. Plug both into the root
`backend.tf` (via `-backend-config=` or by editing the file directly)
and then:

```bash
cd ..
terraform init -backend-config="bucket=$(terraform -chdir=bootstrap output -raw state_bucket)"
```

## Day-to-day

```bash
terraform workspace select dev
terraform plan  -var-file=environments/dev/terraform.tfvars -var="image_tag=main-latest"
terraform apply -var-file=environments/dev/terraform.tfvars -var="image_tag=main-latest"
```

CI passes `image_tag` based on the git SHA + subsystems hash; human
operators usually want the `latest` convenience tag.

## Conventions

- Every resource gets `environment`, `service`, `managed_by = terraform`
  via `default_tags`.
- Plural resources use `for_each`; no copy-paste. Adding a new KMS key
  is a one-liner in `locals.kms_purposes`.
- Secrets are created with placeholder values
  (`"__uninitialised__"`) and a `lifecycle.ignore_changes` on the
  version. Real plaintext is loaded out-of-band per the
  deployment runbook (`docs/deployment/aws.md`).
- No long-lived AWS credentials. CI uses GitHub OIDC. Only one
  workspace per account should set `manage_github_oidc_provider = true`
  (the first one Terraform'd).
- Provider versions pinned at the minor level (`~> 5.40`). Upgrading
  happens in a deliberate PR, not as a side effect of
  `terraform init -upgrade`.

## Outputs to know

| Output | Used by |
|---|---|
| `api_endpoint` | Curl against during smoke tests / readyz probes. |
| `ecr_repositories` | CI image push; manual image push. |
| `secret_arns` | Operators seeding placeholder values. |
| `audit_bucket_name` | S3-facing tooling; lifecycle audits. |
| `ld_relay_url` | Populates `STC_LD_RELAY_URL` in task envs. |
| `amp_remote_write_endpoint` | ADOT collector config; Grafana data source. |
| `github_deploy_role_arn` | Paste into `.github/deploy-matrix.yaml`. |

## Common gotchas

- **Object Lock cannot be retrofitted**: the S3 audit bucket enables
  Object Lock AT CREATION. Do not try to import an existing bucket.
- **Aurora + ElastiCache dependency on Secrets Manager**: seed the
  `rds_master_password` and `redis_auth_token` secret versions BEFORE
  running `apply` on the `rds` / `elasticache` modules.
- **ECR lifecycle policy drift**: the per-repo policy is set once at
  create; recreating the repo loses history. Plan for this when
  switching between `IMMUTABLE` and `MUTABLE`.
- **Cloud Map namespace ownership**: the `qdrant` module creates the
  `stc.internal` namespace and the `ld_relay` module looks it up.
  Apply `qdrant` before `ld_relay` on first run (Terraform will order
  this correctly given the dependency graph; listed here so a manual
  re-plan doesn't confuse it).
