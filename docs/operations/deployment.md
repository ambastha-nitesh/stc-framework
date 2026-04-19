# Deployment

## Library embedding

```python
from stc_framework import STCSystem

system = STCSystem.from_env()   # or from_spec("path.yaml")
```

`STCSystem` is process-wide, thread-safe, and re-entrant. Share a single
instance across all request handlers. Create it once during process
startup and reuse it.

## HTTP service

```bash
pip install "stc-framework[service]"
gunicorn -k gthread --threads 8 -w 4 \
    --bind 0.0.0.0:8000 \
    "stc_framework.service.wsgi:application"
```

**Worker sizing.** The reference service uses threaded gunicorn workers.
Each worker spawns its own asyncio event loop thread that owns the
`STCSystem`; Flask request threads submit coroutines to that loop and
wait on futures. For CPU-bound concurrency, scale `-w`; for IO concurrency
within a worker, scale `--threads` *and* `STC_LLM_BULKHEAD` /
`STC_VECTOR_BULKHEAD`.

A conservative starting point for a 4 vCPU box running LLM-heavy workloads:

```
-w 4 --threads 16
STC_LLM_BULKHEAD=128
STC_VECTOR_BULKHEAD=128
STC_EMBEDDING_BULKHEAD=128
```

## Full stack with Docker

```bash
docker-compose up -d         # qdrant + ollama + presidio + litellm + phoenix + langfuse
pip install -e ".[all]"
STC_LLM_ADAPTER=litellm \
STC_VECTOR_ADAPTER=qdrant \
STC_EMBEDDING_ADAPTER=ollama \
STC_OTLP_ENDPOINT=grpc://localhost:4317 \
  stc-agent --spec spec-examples/financial_qa.yaml
```

## Horizontal scaling

- Switch `STC_HISTORY_STORE=sqlite` and point multiple workers at the
  same `history.db` if you need the Trainer's optimization signals to be
  shared across a pool. For larger deployments, implement a custom
  `HistoryStore` backed by Postgres/ClickHouse.
- The Critic's escalation state is per-process by default; for global
  quarantine, plug in a shared `EscalationStore`.
- The audit backend can shard by date (default JSONL) or be replaced by a
  durable streaming backend (Kafka / Kinesis).
