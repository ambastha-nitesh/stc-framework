# Multi-tenancy

## Tenant identification

- **Library callers** pass `tenant_id` into `aquery(..., tenant_id=...)`.
- **HTTP service** reads `X-Tenant-Id` from the request.
- The value propagates via a `ContextVar` and appears on every log
  record, trace span, and audit record.

## Per-tenant metrics

`stc_queries_total`, `stc_cost_usd_total`, and
`stc_guardrail_failures_total` all carry tenant labels so Grafana can
slice usage / spend / quality per customer.

## Per-tenant audit

Each `AuditRecord` carries `tenant_id`. The default JSONL backend stores
every tenant's events in the same file partitioned by day; if you need
hard isolation, swap in a custom `AuditBackend` that sharded by tenant.

## Per-tenant rate limits

`flask-limiter` is configured to key on `X-Tenant-Id`. Replace the
default `memory://` storage with `redis://` for shared limits across a
fleet.

## Virtual keys

`VirtualKeyManager` issues scoped keys per persona
(`sk-stalwart-<uuid>`). For per-tenant keys, call `issue(persona, scopes)`
with tenant-specific scopes (e.g. `"tenant:acme-1:llm:call"`) and enforce
them in your auth middleware before dispatching to `STCSystem.aquery`.

## PII and tenant isolation

Presidio redaction runs before the LLM sees any content, so cross-tenant
data leakage via model fine-tuning is minimized. For `restricted` tier
data, the Sentinel additionally tokenizes sensitive values with an
HMAC-keyed surrogate so logs and downstream services never see the
original. Detokenization happens only in-process on the response path.
