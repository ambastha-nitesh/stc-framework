# STC Framework — Enterprise Readiness & Observability Audit

This document records the enterprise-risk and observability review and
the controls added in response. Every finding has a regression test in
`tests/unit/test_enterprise.py` or `tests/unit/test_observability.py`.

---

## E1 — Incomplete metric coverage

**Finding.** The Prometheus export only recorded `stc_queries_total`
for queries that completed through the full pipeline. Queries blocked
at the input rail, retention sweeps, DSAR exports, and erasure calls
left no trace in metrics. Operators could not alert on:

- `rate(blocked_at_input_queries)` to spot injection storms,
- `rate(dsar_exports)` to catch runaway compliance automation,
- `rate(retention_sweeps)` to confirm retention is running.

**Mitigation** (`stc_framework.observability.metrics`):

- `stc_queries_total{action}` now carries a `block_input` action for
  queries rejected pre-LLM.
- New `stc_governance_events_total{event_type}` bumps on every audit
  record, so every `AuditEvent` (26 types) surfaces as a Prometheus
  signal.
- `stc_stage_latency_ms{stage}` histogram — per-stage latency for
  `input_rails`, `stalwart`, `output_rails`. Lets operators pinpoint
  which stage a p99 regression lives in.
- `stc_inflight_requests` gauge — saturation signal.
- `stc_adapter_healthcheck{adapter}` gauge — last result for each
  adapter's health probe.
- `stc_system_info{service_version,spec_version,env}` static info
  gauge so dashboards always have the build context.
- `stc_tenant_budget_usd{tenant,window}` and
  `stc_tenant_budget_rejections_total{tenant,window}` — per-tenant
  spend / rejections.

**Regression tests:** `TestMetricsExist`.

---

## E2 — Metric cardinality explosion via tenant labels

**Finding.** Every metric with a `tenant` label used the raw tenant
ID. A deployment with 10 000 tenants — especially where the ID is an
email or customer slug — would blow up Prometheus TSDB in weeks.

**Mitigation.** `stc_framework.observability.metrics.tenant_label(id)`:

- Passes through short, label-safe IDs unchanged
  (alnum + `-_`, ≤ 32 chars).
- Hashes everything else to `t-<8 hex chars>` so cardinality is
  bounded at 2^32, regardless of tenant count.
- Exposes `set_known_tenants({...})` to pin a small set of
  label-verbatim tenants for customer-facing dashboards.

Every write in the system goes through `tenant_label()`; no raw tenant
IDs leak into Prometheus.

**Regression tests:** `TestTenantLabelCardinality`.

---

## E3 — Spans were orphaned from correlation context

**Finding.** Individual components (`stalwart.run`, `critic.evaluate`,
`sentinel.completion`) created their own root spans. There was no
shared parent, so traces for one query were scattered across multiple
unrelated trees in the OTel backend.

**Mitigation.** `STCSystem.aquery` now opens a single `stc.aquery`
parent span and binds `trace_id`, `request_id`, `tenant_id`, and
`spec_version` as attributes. Every downstream span (`gateway`,
`stalwart.run`, `critic.*`) becomes a child automatically because
`start_as_current_span` respects the active context.

Logs also carry `span_id` via the structlog `_bind_otel_context`
processor, so you can pivot log → trace in Grafana.

**Regression tests:** `TestCorrelationBinding`.

---

## E4 — `/readyz` was a lie

**Finding.** The Flask readiness endpoint only consulted
`DegradationState`. An LLM outage that had not yet caused a
circuit-breaker transition would still return 200 — the pod would
serve traffic into a dead provider until the breaker tripped.

**Mitigation.** `stc_framework.observability.health.probe_system`
runs each adapter's `healthcheck()` with a short per-adapter timeout
and returns an aggregated report. `/readyz` now returns 503 the
moment any adapter probe fails, `stc_adapter_healthcheck{adapter}`
flips to 0, and Kubernetes / ALB can yank the pod out of the
backend pool.

Exposed both at library level (`STCSystem.ahealth_probe`) and HTTP
(`GET /readyz`).

**Regression tests:** `TestHealthProbe`, `TestStartupFailFast`.

---

## E5 — No per-tenant budget enforcement

**Finding.** The spec declared `trainer.cost_thresholds.daily_budget_usd`
but there was no code to enforce it. One tenant with a runaway loop
could exhaust the global budget for everyone; the Trainer's
maintenance triggers noticed, but after the money was already spent.

**Mitigation.** `stc_framework.governance.budget.TenantBudgetTracker`:

- Records every `stalwart.cost_usd` against a rolling per-tenant
  window.
- `STCSystem.aquery` calls `_budget.enforce(tenant_id)` before any
  LLM work; if the tenant has exhausted their daily or monthly cap,
  the request is rejected with `STCError(reason="tenant_budget_exceeded")`.
- Rejection is audited (`query_rejected` event with the observed vs
  limit) and counted via `stc_tenant_budget_rejections_total`.
- `erase_tenant` also drops budget samples so right-to-erasure
  doesn't leave orphaned accounting.

Plug a Redis / DB-backed store in place of the default in-memory
tracker for multi-process deployments (subclass
`TenantBudgetTracker` and pass via DI).

**Regression tests:** `TestBudgetTracker`, `TestBudgetSystemIntegration`.

---

## E6 — No idempotency support

**Finding.** API clients and retrying proxies re-send the same
request routinely. With no idempotency, each retry re-charged the
tenant, re-audited, and re-counted — corrupting both metrics and
accounting.

**Mitigation.** `stc_framework.governance.idempotency.IdempotencyCache`:

- LRU + TTL cache keyed by `(tenant_id, idempotency_key)`.
- `STCSystem.aquery(..., idempotency_key=...)` returns the cached
  `QueryResult` on a repeat, so trace_id, metadata, and audit are
  stable across retries.
- Empty keys disable the cache (backwards compatible with callers
  that don't send one).
- `erase_tenant` drops cached entries for the subject.

**Regression tests:** `TestIdempotency`.

---

## E7 — No graceful shutdown

**Finding.** `STCSystem.astop()` closed the audit log immediately.
Any in-flight query was torn off mid-write — causing partial audit
records, lost responses, and client-visible 5xx during rolling
deploys.

**Mitigation.**

- New `InflightTracker` counts active queries (exposed via
  `stc_inflight_requests`).
- `STCSystem.aquery` wraps its pipeline in `inflight.track()`.
- `STCSystem.astop(drain_timeout=30)` sets a `_stopping` flag (so new
  requests return 503-eqiuivalent), then awaits
  `inflight.wait_idle(drain_timeout)` before closing the audit log.
- Returns `True` if cleanly drained, `False` on timeout, so
  orchestrators can decide whether to force-kill.

**Regression tests:** `TestGracefulShutdown`.

---

## E8 — No startup fail-fast

**Finding.** Previously the system started successfully even with
unreachable dependencies; only the first real query would discover
the outage, causing noisy 5xx spikes in the first seconds after a
deploy.

**Mitigation.**

- `STCSystem.astart(strict_health=True, health_timeout=2.0)` probes
  every adapter at startup. If any fails, the call raises
  `STCError("startup health check failed: ...")`. Point your
  Kubernetes `startupProbe` at `/readyz` with reasonable retries
  and failed pods never enter the pool.
- Non-strict mode still starts, but the first `/readyz` call
  observes the outage.
- Both modes emit a `system_start` audit event with the per-adapter
  result.

**Regression tests:** `TestStartupFailFast`.

---

## Observability signal reference

### Metrics

| Metric | Type | Labels | What it means |
|---|---|---|---|
| `stc_queries_total` | counter | `persona,tenant,action` | Query throughput by outcome (`pass`/`warn`/`block`/`block_input`/`escalate`) |
| `stc_latency_ms` | histogram | `persona,stage` | End-to-end request latency |
| `stc_stage_latency_ms` | histogram | `stage` | Per-stage latency (`input_rails`/`stalwart`/`output_rails`) |
| `stc_llm_tokens_total` | counter | `model,direction` | Token usage |
| `stc_cost_usd_total` | counter | `model,tenant` | Cumulative spend |
| `stc_tenant_budget_usd` | gauge | `tenant,window` | Current tenant spend in window |
| `stc_tenant_budget_rejections_total` | counter | `tenant,window` | Tenant-budget rejections |
| `stc_guardrail_failures_total` | counter | `rail,severity` | Critic failures |
| `stc_escalation_level` | gauge | — | 0 normal, 1 degraded, 2 quarantine, 3 paused |
| `stc_circuit_breaker_state` | gauge | `downstream` | 0 closed, 1 half-open, 2 open |
| `stc_bulkhead_rejections_total` | counter | `bulkhead` | Back-pressure events |
| `stc_retry_attempts_total` | counter | `downstream,outcome` | Retry behavior |
| `stc_redaction_events_total` | counter | `entity_type` | PII redactions |
| `stc_boundary_crossings_total` | counter | `from_tier,to_model` | Data-tier crossings |
| `stc_governance_events_total` | counter | `event_type` | Count of audit events |
| `stc_inflight_requests` | gauge | — | Saturation |
| `stc_adapter_healthcheck` | gauge | `adapter` | Last healthcheck result |
| `stc_system_info` | gauge | `service_version,spec_version,env` | Static build info |

### Alerting rules (suggested)

```yaml
# Error budget
- alert: stc_query_block_rate_high
  expr: |
    sum(rate(stc_queries_total{action=~"block|block_input"}[5m]))
    / sum(rate(stc_queries_total[5m])) > 0.05
  for: 10m

# Saturation
- alert: stc_bulkhead_rejections
  expr: sum(rate(stc_bulkhead_rejections_total[5m])) > 0
  for: 2m

# External dependency down
- alert: stc_circuit_open
  expr: max(stc_circuit_breaker_state) == 2
  for: 1m

# Cost runaway
- alert: stc_tenant_near_budget
  expr: stc_tenant_budget_usd / on(tenant) group_left
        avg_over_time(stc_tenant_budget_usd[1h]) > 3
  for: 15m

# Governance escalation
- alert: stc_escalation_active
  expr: stc_escalation_level > 0
  for: 5m
```

### Tracing

Every query opens a single `stc.aquery` parent span with attributes:

- `stc.trace_id` (business trace id)
- `stc.request_id`
- `stc.tenant_id`
- `stc.spec_version`
- `stc.action` (final outcome)
- `stc.model_used`

Child spans:

- `critic.input_rails`
- `stalwart.run` → `stalwart.classify|retrieve|assemble_context|reason|format_response`
- `sentinel.completion`
- `critic.output_rails`

Set `STC_OTLP_ENDPOINT=grpc://otel-collector:4317` to ship.

### Logs

Structured JSON with the following bound fields on every record
(via structlog processors):

- `trace_id`, `span_id` (from OTel)
- `request_id`, `tenant_id`, `persona`, `prompt_version` (from `contextvars`)
- `timestamp` (UTC ISO)
- `level`
- `logger`

PII-risk keys (`query`, `response`, `content`, `prompt`, `user_input`)
are auto-dropped unless `STC_LOG_CONTENT=true`.

### Audit

Every audit record (26 event types) is hash-chained and tamper-evident.
Alert if `verify_chain` fails or if `governance_events_total`
drops to zero (indicates the audit pipeline is broken).

---

## Runbook

### Pod fails readiness on startup

1. `curl -s $HOST/readyz | jq` — which adapter is red?
2. Check `stc_adapter_healthcheck{adapter=X}` in Prometheus.
3. If LLM: inspect LiteLLM proxy logs.
4. If vector_store: `curl $QDRANT/collections`.
5. If embeddings: Ollama `docker logs`.
6. Retry with `strict_health=False` to serve from local fallbacks
   until the dependency is back.

### Saturation

1. `stc_inflight_requests` rising monotonically → pod can't keep up.
2. `stc_bulkhead_rejections_total{bulkhead=X}` rising → internal
   concurrency cap hit. Raise `STC_<X>_BULKHEAD` or scale out.
3. `stc_stage_latency_ms{stage=X}` p99 spiking → isolate which stage
   and drill into spans for the outlier trace.

### Tenant runaway

1. `stc_tenant_budget_rejections_total{tenant=X}` > 0 → tenant was
   cut off.
2. `stc_cost_usd_total{tenant=X}` spike vs baseline → investigate
   client code for retry loops or prompt inflation.
3. `stc_queries_total{tenant=X,action="block_input"}` high →
   suspicious traffic; check `rail_failed` audit events for pattern.

### Audit chain broken

1. Run `python -c "from stc_framework.observability.audit import verify_chain; from stc_framework.adapters.audit_backend.local_file import JSONLAuditBackend; ok,n,why = verify_chain(JSONLAuditBackend('/path/to/audit').iter_records()); print(ok, n, why)"`.
2. Compare the last sealed hash on disk with the sibling replica
   (if you ship audit records to a secondary store).
3. If tampering confirmed: quarantine the node, rotate keys,
   declare the incident per your SOC 2 / breach-notification workflow.

---

## Running the audit

```bash
pip install -e ".[dev,service]"
pytest tests/unit/test_observability.py tests/unit/test_enterprise.py -v
```

All tests must pass before a release. The two suites cover:

- metric existence, cardinality, per-stage labels
- correlation context propagation
- adapter healthcheck plumbing
- budget enforcement end-to-end
- idempotency replay
- graceful shutdown drain
- strict startup fail-fast
