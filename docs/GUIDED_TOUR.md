# Guided Tour

A 10-minute read for a new engineer. Files listed in the order that
will make the codebase click fastest — **not** alphabetical, not the
order `tree src/` would show.

## Minute 1 — Start at the contract: the spec

Open `spec-examples/financial_qa.yaml`.

Every runtime policy is here. Read the sections in order:

- `stalwart` — tool list, memory config, auth scope.
- `trainer` — cost thresholds, maintenance triggers.
- `critic.guardrails.input_rails` and `output_rails` — what runs on
  every query.
- `data_sovereignty.routing_policy` — which models are allowed for
  which data tier.
- `audit.retention_policies` — per-event retention (not a single knob).

This YAML, not the code, is what auditors review. When the code and
the spec disagree, the spec is authoritative and the code is a bug.

## Minute 2 — See the whole pipeline as one function

Open `src/stc_framework/system.py`. Find `STCSystem.aquery`.

Read top to bottom. The order of operations is the whole architecture
in 80 lines:

1. Input-size / type / Unicode guards.
2. Sanitise `tenant_id` and `idempotency_key`.
3. Idempotency cache hit → short-circuit.
4. Shutdown / degradation guards.
5. Rate limit.
6. Budget reserve.
7. Set correlation context.
8. Input rails (Critic).
9. Stalwart pipeline.
10. Output rails (Critic).
11. Settle budget; emit audit; return.

Every defensive control in the system is one of those eleven steps.

## Minute 3 — Meet the three personas

- `stalwart/agent.py::StalwartAgent` — the execution pipeline. Read
  `arun()` — it's ~30 lines.
- `critic/critic.py::Critic` — the governance orchestrator. Read
  `aevaluate_output()` — it calls the `RailRunner`, aggregates results,
  handles escalation.
- `trainer/trainer.py::Trainer` — the optimization coordinator. Read
  `on_trace()` — records history + feeds Agent Lightning.

Note what each does **not** do:

- Stalwart does not know any rail exists.
- Critic does not call an LLM.
- Trainer does not change runtime state directly; it writes through
  controllers.

## Minute 4 — The Sentinel: where policies become calls

Open `sentinel/gateway.py::SentinelGateway.acompletion`. This is the
*only* function in the whole system that actually sends a request to
an LLM provider.

Read the sequence inside:

1. Classify the query's data tier.
2. Redact PII.
3. Pick a model from `routing_policy[tier]`.
4. Refuse if the restricted tier contains a non-local model (defence
   in depth — the spec validator already enforced this at load time).
5. Run with retry + circuit breaker + timeout + bulkhead + fallback.
6. Detokenize the response (if we tokenized on the way in).
7. Emit the audit record, including a `boundary_crossing` flag.

If you're ever asked "how does the framework guarantee restricted data
stays local?" — point them to this function.

## Minute 5 — Validators, the most-likely place to edit

Open `critic/validators/` and read any one file, say `numerical.py`.

Every validator has the same shape:

```python
class MyValidator(Validator):
    rail_name = "my_rail"        # String key the spec references
    severity = "high"            # Drives action (critical=block, etc.)

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        ...
```

The `ValidationContext` carries `query`, `response`, `context`,
`retrieved_chunks`, `trace_id`, `data_tier`. Your `GuardrailResult`
carries a pass/fail, severity, action, details string, and evidence
dict.

Every validator is registered in `critic/critic.py::__init__` under
the same string key the spec uses.

## Minute 6 — The audit log is the compliance artifact

Open `observability/audit.py`. `AuditRecord` is the pydantic model.
`verify_chain` walks a sequence and checks the HMAC hash chain.

Backends:

- `adapters/audit_backend/local_file.py::JSONLAuditBackend` — the
  default. Supports `erase_tenant` (GDPR) and `prune_before`
  (retention).
- `adapters/audit_backend/worm.py::WORMAuditBackend` — for SEC
  17a-4. Refuses prune and erase with `ComplianceViolation`.

The hash chain isn't just decoration — read `compute_entry_hash`.
An attacker without the HMAC key cannot produce an `entry_hash` that
verifies, which is the point.

## Minute 7 — Governance surface: DSAR, erasure, retention, budget

Open `governance/`. Five files, each narrow:

- `events.py` — enum of every auditable action. New events go here.
- `dsar.py` — GDPR Art. 15 tenant-data export.
- `erasure.py` — GDPR Art. 17 tenant-data erasure. Touches EVERY
  tenant-scoped store (audit, history, vectors, tokens, idempotency,
  budget, rate limiter). If you add a new tenant-aware store you must
  teach erasure about it.
- `retention.py` — per-event-class retention with "forever" classes
  for chain seals.
- `budget.py` — per-tenant cost tracking with calendar-day buckets and
  a monotonic-clock sanity check.
- `rate_limit.py` — per-tenant RPS (token bucket).
- `idempotency.py` — LRU-TTL cache, keyed by (tenant_id, key).

## Minute 8 — Tests are the contract

Run:

```bash
pytest tests/unit/test_security.py tests/unit/test_privacy.py \
       tests/unit/test_observability.py tests/unit/test_enterprise.py \
       tests/unit/test_staff_review.py tests/unit/test_staff_review_round2.py
```

Six files, each one the regression suite for one audit round. Any
failure is a release blocker. When you're about to "simplify" some
code that looks odd, run these first.

`tests/conftest.py` has the `minimal_spec` + `financial_spec` fixtures
and the autouse fixtures that reset the global state between tests.

## Minute 9 — Observability surface

`observability/`:

- `audit.py` — already covered.
- `metrics.py` — Prometheus counters. `tenant_label()` hashes
  high-cardinality tenant IDs. `get_metrics()` is the singleton.
- `tracing.py` — OpenTelemetry. `init_tracing()` is idempotent.
- `correlation.py` — `ContextVar`s for trace/tenant/request/persona.
  Every log and every span pulls from here.
- `health.py` — `probe_system()` calls each adapter's `healthcheck()`.
- `inflight.py` — `InflightTracker.wait_idle()` backs graceful
  shutdown.

## Minute 10 — Where to edit for the five most likely tasks

| Task | Primary file | Secondary |
|---|---|---|
| Add a Critic rail | `critic/validators/<name>.py` | Register in `critic.py::__init__`; add spec entry; add test |
| Add an LLM provider | `adapters/llm/<name>.py` | Add settings literal; map errors to `errors.py` |
| Add a new audit event | `governance/events.py::AuditEvent` | Optional retention class in `spec/models.py::RetentionPolicy` |
| Add an audit backend | `adapters/audit_backend/<name>.py` | Register in `system.py::_build_default_audit_backend` |
| Change retention for a class | Edit `RetentionPolicy` in the spec YAML | Update `DECISIONS.md` if justified |

---

You have now been on every floor of the building. For the next week,
when you open a file for the first time, come back to this tour.
Things that seemed arbitrary should now have a shape.
