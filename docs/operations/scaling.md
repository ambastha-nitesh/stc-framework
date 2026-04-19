# Scaling

## Single-process

`STCSystem` is thread-safe and allocates heavy resources (Presidio,
embedder, vector store handles) once. Share one instance across all
threads. Recommended: one instance per gunicorn worker, plus internal
asyncio concurrency via bulkheads.

## Horizontal

The default in-memory stores (history, escalation, token store, audit)
do not share state across processes. For a fleet of workers:

| State | Default | Scaling backend |
|---|---|---|
| Performance history | `InMemoryHistoryStore` | `SQLiteHistoryStore` (single node) or custom Postgres store |
| Escalation failures | In-memory | Custom `EscalationStore` (Redis / Postgres) |
| Token store | `InMemoryTokenStore` | `EncryptedFileTokenStore` (single node) or external vault |
| Audit | Rotating JSONL | Parquet export or custom streaming backend |
| Prompt registry | `FilePromptRegistry` | `LangfuseAdapter` (optional extra) |

## Rate limiting

The Flask service uses `flask-limiter` keyed by `X-Tenant-Id` (falling
back to remote address). Plug your API gateway in front for per-plan
quotas.

## Cost management

`stc_cost_usd_total` is labelled by tenant. Set per-tenant budgets in
your monitoring stack and alert when spend approaches
`trainer.cost_thresholds.daily_budget_usd`. The Trainer's
`MaintenanceExecutor` can automatically down-route to cheaper models via
`RoutingController.apply()` when `cost_above_per_task_usd` is tripped.
