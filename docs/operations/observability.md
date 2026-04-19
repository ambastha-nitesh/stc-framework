# Observability

## Metrics (Prometheus)

| Metric | Type | Labels | Purpose |
|---|---|---|---|
| `stc_queries_total` | counter | `persona`, `tenant`, `action` | Throughput, action mix |
| `stc_latency_ms` | histogram | `persona`, `stage` | End-to-end and per-stage latency |
| `stc_cost_usd_total` | counter | `model`, `tenant` | Per-tenant LLM spend |
| `stc_llm_tokens_total` | counter | `model`, `direction` | Token usage |
| `stc_guardrail_failures_total` | counter | `rail`, `severity` | Governance failures |
| `stc_escalation_level` | gauge | — | 0 normal, 1 degraded, 2 quarantine, 3 paused |
| `stc_circuit_breaker_state` | gauge | `downstream` | 0 closed, 1 half-open, 2 open |
| `stc_redaction_events_total` | counter | `entity_type` | PII redaction rate |
| `stc_boundary_crossings_total` | counter | `from_tier`, `to_model` | Data-tier crossings |
| `stc_bulkhead_rejections_total` | counter | `bulkhead` | Backpressure events |
| `stc_retry_attempts_total` | counter | `downstream`, `outcome` | Retry behavior |

Expose with:

```python
from stc_framework.observability.metrics import start_metrics_server
start_metrics_server(port=9090)
```

Or via the Flask service's `/metrics` endpoint.

## Tracing (OpenTelemetry)

Set `STC_OTLP_ENDPOINT` to enable OTLP export. Every span carries:

- `service.name`, `service.version`, `stc.spec_version`
- `stc.data_tier`, `stc.model_used`, `stc.boundary_crossing`
- `stc.redactions`, `stc.citations.count`

## Logs (structlog JSON)

Every record includes `trace_id`, `span_id`, `request_id`, `tenant_id`,
`persona`, and `prompt_version` via `contextvars`. PII keys (`query`,
`response`, `content`, `prompt`, `user_input`) are redacted unless
`STC_LOG_CONTENT=true`.

## Audit

`AuditRecord` is an immutable pydantic model; the default backend writes
rotating daily JSONL under `STC_AUDIT_PATH`. Every boundary crossing,
LLM call, guardrail result, and escalation transition is logged.
Daily parquet exports are available via
`stc_framework.adapters.audit_backend.parquet_export.export_jsonl_to_parquet`.
