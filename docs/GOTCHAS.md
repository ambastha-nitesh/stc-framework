# Gotchas

Things that look like bugs but aren't, things that will bite you once,
and things where "making the code simpler" would break something real.

---

## Audit / compliance

### `erase_tenant()` exists AND refuses to exist, depending on backend

`JSONLAuditBackend.erase_tenant` deletes tenant rows and recomputes the
hash chain (GDPR Art. 17).

`WORMAuditBackend.erase_tenant` raises `ComplianceViolation` (SEC
17a-4).

Both are correct. The deployer picks one via `STC_AUDIT_BACKEND`.
Neither is "the wrong answer" — they're answers for different
regulatory regimes. Do not "unify" them.

### `verify_chain` has two modes and they are not interchangeable

- `verify_chain(records)` — strict, expects `prev_hash == "0"*64` on
  the first record. Correct for a full cold verification from the
  original genesis.
- `verify_chain(records, accept_unknown_genesis=True)` — post-prune
  mode. The first surviving record's `prev_hash` points to a record
  that retention deleted. Strict mode will fail here; that's not a
  tamper event.

Use strict for compliance audits against a log that has never been
pruned. Use the relaxed mode anywhere retention has run.

### The audit HMAC key has an "ephemeral" fallback — in dev only

`_KeyManager` generates a random key per process when
`STC_AUDIT_HMAC_KEY` is unset. This keeps dev tooling working but
means chains written by one process can't be verified by another.
`STC_ENV=prod` refuses to start under this condition. Do not treat
ephemeral mode as equivalent to a real deployment.

### `rail_failed` events retain for 6 years, but only if the default
### `RetentionPolicy` hasn't been overridden

`retention_policies` in the spec has class-specific defaults. A spec
that sets only `retention_days: 30` without `retention_policies: {...}`
still gets 6-year retention on erasure receipts — the pydantic default
kicks in for the un-set fields. This is intentional: a generic number
cannot accidentally delete compliance evidence.

---

## Observability

### Correlation (trace_id, tenant_id) is in `contextvars`, not args

If you need `trace_id` inside a brand-new function, import
`current_correlation()` from `observability.correlation` — do not
thread it through the call signature. Adding a `trace_id` parameter to
a public API is nearly always a mistake.

### `bind_correlation` is a context manager, not a decorator

The correct pattern:

```python
with bind_correlation(trace_id="stc-xyz", tenant_id="t1"):
    do_work()
```

It looks like a decorator should be equivalent, but `ContextVar`
doesn't propagate cleanly across decorator boundaries in all async
cases. Use the context manager.

### Metric registration is process-global

`get_metrics()` returns a singleton. Two `STCSystem` instances in the
same process share metric counters. For test isolation, conftest
resets the registry. For production, run one `STCSystem` per process.
See the STAFF_REVIEW.md Tier-2 item S9 for the roadmap fix.

### Prometheus Counter names vs sample names

`stc_queries_total` is the Counter; its family name is `stc_queries`
(no suffix) and the sample name is `stc_queries_total`. Filters that
match on `family.name` will miss Counters. Use `sample.name` startswith
when walking the registry.

---

## Concurrency

### `async with self._inflight.track()` wraps the *entire* pipeline

If you refactor `aquery` and split the pipeline into functions, the
inflight tracker must still wrap the whole flow. Moving the `async
with` inside a helper and forgetting to acquire in the outer method
will cause `astop(drain_timeout=...)` to never drain anything.

### Budget `reserve` holds the lock across the check AND the book

Plain `enforce + record_cost` has a TOCTOU race under concurrent
requests from the same tenant. Always use `reserve` in the hot path;
`record_cost` is only for post-hoc corrections.

### The `_stopping` flag matters before `degradation.allow_traffic`

`STCSystem` sets `_stopping=True` in `astop` before waiting on drain.
`aquery` checks it early. Reordering these — e.g., checking degradation
first — means requests that slip in during shutdown may still reach
the LLM.

---

## Config / startup

### `STC_ENV` controls enforcement mode, not log verbosity

Setting `STC_ENV=prod` on a laptop will fail startup with six different
"must be set" errors. This is the point. Use `dev` (default) locally.

### Presidio warm-up is silent on failure

`_warm_adapters` calls `redactor.redact("warmup")` inside
`asyncio.to_thread` and swallows exceptions. Under normal operation,
this makes the first real query 1-2 seconds faster. If Presidio is
mis-configured, startup still succeeds and the first query pays the
cold-start cost. To verify Presidio really loaded, call
`ahealth_probe()` and inspect the `presidio` adapter result.

### The HashEmbedder is not a real embedder

`HashEmbedder` produces deterministic but semantically meaningless
vectors. It exists so that `pip install stc-framework` + 60 seconds of
code gets you a working end-to-end demo. It is explicitly *not* for
production. Under `STC_ENV=prod` you must set
`STC_EMBEDDING_ADAPTER=ollama` (or similar) and supply a real
endpoint.

---

## Validators / rails

### Rail `name` is a class attribute, not a constructor arg

```python
class MyValidator(Validator):
    rail_name = "my_rail"     # Class attribute — stable identifier
    severity = "high"         # Also class attribute
```

The spec references `critic.guardrails.output_rails[*].name` and the
Critic looks up the validator by that exact string. Renaming the class
attribute breaks every spec that uses it. Think of it like a primary
key.

### The spec's rail entries accept extra fields silently

`GuardrailRailSpec` has `model_config = ConfigDict(extra="allow")`.
That means a typo like `tolerence_percent` (instead of
`tolerance_percent`) loads as a spec-level extra and is silently
ignored. Your rail won't see the value. Always read the validator's
`__init__` to find the real field names before changing the spec.

### `rail_by_name` is memoized; mutating the spec post-load is a bad
### idea

`STCSpec` caches the rail index on first lookup. Mutating
`spec.critic.guardrails.output_rails.append(...)` after the cache is
warm does not update `_rail_index`. Build a new `STCSpec` instead.

---

## Sentinel / data sovereignty

### `is_local_model` treats `bedrock/` as in-boundary

Because customer-VPC Bedrock is in the trust boundary. If you wire an
adapter that sends traffic to public Bedrock endpoints, update
`spec/routing_guard.py::_LOCAL_PREFIXES` or introduce a more nuanced
check — a naive `bedrock/...` model string will silently pass the
restricted-tier guard.

### `set_routing_preference` refuses unknown models

The Trainer can only reorder models already declared in the spec's tier
— it cannot smuggle in a new provider. A compromised Trainer cannot
insert "evil/openai-proxy" into the `restricted` list. If you genuinely
want to add a new model, it goes in the spec, not through the Trainer.

### PII redaction runs on retrieved chunks, not only user queries

`StalwartAgent._retrieve` runs `chunk_redactor.redact()` on every chunk
before context assembly. If a chunk contains `BLOCK`-listed PII (SSN,
credit card) the chunk is dropped — *not* the whole query. You can
lose relevant context and get a worse answer. This is the right
tradeoff for regulated deployments; document it on your customer-facing
answer-quality SLO.

---

## Testing

### `stc_framework.testing` refuses to run in prod

`reset_metrics`, `reset_circuits`, `reset_degradation`,
`reset_audit_hmac_key` all raise if `STC_ENV=prod`. This prevents a
test-adjacent import from clobbering real production state. It also
means your test helpers cannot be used in a staging process to
"recover from a bad metric state" — file an ops ticket instead.

### `minimal_spec` is different from `financial_spec`

Two fixtures. `minimal_spec` is the test-only YAML at
`tests/fixtures/minimal_spec.yaml` — small rail set, deterministic.
`financial_spec` loads the real `spec-examples/financial_qa.yaml`. Use
`minimal_spec` in unit tests; use `financial_spec` only when you
explicitly want to catch schema drift against the shipped example.

### Tests rely on a per-test fresh `CollectorRegistry`

Never call `get_metrics()` at module import time. The conftest's
autouse fixture rebinds the singleton per test, and module-level
`get_metrics()` binds to the registry that existed when your module
was imported — which is then stale for every subsequent test.

---

## Flask service

### SIGTERM triggers a 30-second drain, not an immediate shutdown

Kubernetes `preStop` sends SIGTERM. Our handler calls
`runner.shutdown(drain_timeout=30)`. If your pod disruption budget or
`terminationGracePeriodSeconds` is less than 35 s, the orchestrator
will SIGKILL mid-drain and you'll lose in-flight audits. Set
`terminationGracePeriodSeconds: 60` (or higher) for this service.

### `abort(413)` is caught by the generic error handler

Werkzeug `HTTPException` has a dedicated handler that preserves status
codes. If you add new `abort(...)` calls, they route through that
handler — *not* the generic `Exception` handler. The HTTP status you
pass will be honoured.
