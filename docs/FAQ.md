# First-Week FAQ

The questions a new engineer actually asks in their first week.

---

### 1. "There's a Stalwart, a Trainer, a Critic, and a Sentinel. Why four? Can't this be one class?"

You could technically make it one class, but you'd fail the design:
separation of duties is the product, not an implementation detail.

- A Stalwart that evaluates its own output has confirmation bias.
- A Trainer that can directly mutate runtime state is an attack
  surface.
- A single-class system cannot give a regulator the answer "who
  approved this response?".

The four planes are enforced by module boundaries and by the allowed
call graph (see `ARCHITECTURE.md`). If you find yourself calling
Critic code from Stalwart, or vice versa, you're about to violate the
core invariant.

---

### 2. "Why is there both an `in-memory vector store` and a `mock LLM` default? Isn't that insecure?"

The defaults are there so `pip install stc-framework` + 10 lines of
code gets you a running end-to-end system for a demo or a notebook.
They're intentionally obvious mocks:

- `HashEmbedder` produces deterministic-but-semantically-meaningless
  vectors.
- `MockLLMClient` tags every response with `[mock-llm]` so no one
  can confuse it with a real response later.

`STC_ENV=prod` refuses to boot with `STC_LLM_ADAPTER=mock`. If you
ever see `[mock-llm]` in a production audit record, it's a P0 —
someone bypassed the guard.

---

### 3. "I added a rail in `critic/validators/` but nothing happens. Why?"

Two places that both need to know about your rail:

1. The spec YAML under `critic.guardrails.output_rails` (or
   `input_rails`) — with your `rail_name` as the `name` field.
2. `critic/critic.py::Critic.__init__`'s `validators` dict, keyed by
   your `rail_name`.

If you only add it to one, the other silently ignores it. Run
`pytest tests/unit/test_staff_review.py::TestGovernanceCLI` —
that catches some wiring bugs, but not this one. The CONTRIBUTING.md
"Add a rail" checklist has the complete steps.

---

### 4. "Why does `aquery` look like it's doing ten things? Can I split it up?"

It is doing ten things. Each one is a defensive control. The order
matters — each step assumes the earlier steps succeeded:

1. Type / size check → else everything downstream sees unbounded input.
2. Sanitise headers → else control chars poison audit logs.
3. Idempotency → else retries double-charge the tenant.
4. Shutdown flag → else drain never finishes.
5. Degradation guard → else we serve traffic during quarantine.
6. Rate limit → else cost alone is insufficient.
7. Budget reserve → else TOCTOU race on concurrent requests.
8. Correlation bind → else downstream logs are unlinkable.
9. Input rails → else injection reaches the LLM.
10. Pipeline → finally, the actual work.

You can refactor internals (extract helpers, split `_run_pipeline`
further) but the order of the 10 checks is load-bearing. Tests
`test_staff_review.py` and `test_enterprise.py` will catch most
re-ordering errors.

---

### 5. "Why is `verify_chain` different from what the docstring used to say?"

Round-2 of the staff review added `accept_unknown_genesis`. The old
"strict-genesis" mode is still correct for verifying a log that has
never been pruned. But after any `prune_before` call, the first
surviving record's `prev_hash` points to a record that retention
deleted — strict mode would flag that as tampering (false positive).

Operational rule:

- Full compliance audit from genesis: strict mode.
- Any day-to-day integrity check after retention has run:
  `accept_unknown_genesis=True`.

The `retention_prune_seal` records are permanent (`retention: -1`) so
you can always prove a prune happened legitimately; accept-unknown
mode just lets verification jump across that boundary without failing.

---

### 6. "I grep'd for `STCSystem` and there are a lot of methods. Which one is the entry point?"

`aquery(query, *, tenant_id=None, idempotency_key=None)`. Everything
else is a facade.

- `query(...)` — synchronous wrapper; exists for notebooks; refuses to
  run inside a live event loop.
- `aexport_tenant`, `aerase_tenant`, `aapply_retention` — governance
  delegates.
- `astart`, `astop`, `ahealth_probe` — lifecycle.
- `submit_feedback` — trainer feedback.

If you're adding a new control, it belongs inside `aquery` (not
alongside it).

---

### 7. "What is `contextvars` doing everywhere?"

`trace_id`, `request_id`, `tenant_id`, `persona`, `prompt_version` are
all in `ContextVar`s (see `observability/correlation.py`). They're set
by `bind_correlation(...)` as a context manager. Every structured log
line, every OTel span, every audit record reads from the same
`ContextVar` snapshot.

This is why you rarely see these values passed as function
arguments. If you need them somewhere new, import `current_correlation`
— don't add a parameter. The Gotchas doc has the full rationale.

---

### 8. "The spec says `retention_days: 365` but erasure receipts say 6 years. Which wins?"

Both. `retention_days` is a legacy single-value knob kept for
backwards compatibility. `retention_policies` is the per-event-class
map; its defaults in `spec/models.py::RetentionPolicy` are 6-year for
compliance events and forever for chain seals. A spec that doesn't
mention `retention_policies` still gets those defaults.

You would have to explicitly override `retention_policies.erasure` to
get shorter retention on erasure receipts. That's intentional — it
forces the person loosening compliance to declare it.

---

### 9. "How do I reproduce a prod issue locally?"

1. Get the sealed audit records for the trace (they're HMAC-chained
   and have PII redacted).
2. Get the spec that was live during the trace (every record has a
   `spec_version`).
3. Run `STC_ENV=dev STC_AUDIT_HMAC_KEY=<prod-key> python -c "..."` —
   `dev` mode is permissive and `verify_chain` can now read the prod
   records.
4. Replay via `STCSystem.aquery(trace.query, tenant_id=trace.tenant_id,
   idempotency_key=trace.request_id)`.

The `trace_id` and `request_id` in every log line are the same ones in
the audit record — pivot freely.

---

### 10. "Why is there a `testing` subpackage with `reset_*` helpers? Why not just use global state?"

Because global state is what we'd be resetting. `_metrics`,
`_circuits`, `_STATE` (degradation) are all process-global singletons
(see Round-1 STAFF_REVIEW.md Tier-2 item S9 for the roadmap fix).
Tests need a clean slate; `testing.reset_all()` gives them one. The
subpackage refuses to run under `STC_ENV=prod` so a misplaced import
can never clobber production state.

---

### 11. "Why are some validators class attributes (`rail_name`, `severity`) and not __init__ args?"

`rail_name` is the stable identifier the spec references by string.
Making it a class attribute means:

- You can look up a validator class by its rail name without
  instantiating it.
- Renaming the class attribute is a breaking change that's loud —
  every spec using that name stops working.
- You can't accidentally pass a different rail_name at construction
  time and end up with two validators thinking they're the same rail.

It's the same reason SQLAlchemy models have `__tablename__` as a class
attribute, not an `__init__` arg.

---

### 12. "The `_run_pipeline` function has weird indentation. Is that a bug?"

No — it was a bug that was fixed in Round-2 of the staff review. If
you're seeing inconsistent indentation, pull main; if it's still there,
it's the kind of thing a reviewer should flag in PR.

---

### 13. "Why is the cryptography import lazy?"

Because the WORM backend and the tokenization module both use AES-GCM
/ ed25519 / HMAC, but `cryptography` is a heavy import with native
extensions. Lazy import means the 99% of test cases that don't need
crypto don't pay for it.

If you're editing those modules, put the `from cryptography...` import
*inside* the function that uses it. The top-level import is deliberate.
