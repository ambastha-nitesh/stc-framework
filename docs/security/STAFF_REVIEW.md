# STC Framework — Staff-Level Code Review

This document is the output of a "senior / staff engineer" review — the
class of findings a team of experienced reviewers would raise that
haven't come up in the previous specialized rounds (security, privacy,
observability, enterprise).

## Rounds

- **Round 1** — the initial staff review uncovered 7 bugs and a long
  Tier-2 roadmap. Regression tests in `tests/unit/test_staff_review.py`.
- **Round 2** — the pre-deployment review for a FINRA/SEC-regulated
  environment added 5 blockers, 5 nits, and 3 hidden bugs. All 13 are
  fixed; regression tests live in `tests/unit/test_staff_review_round2.py`.

Tier-3 items continue as a roadmap.

---

## Tier 1 — Actual bugs that were fixed

### S1 — `asyncio.timeout` required Python 3.11 but `pyproject.toml` claims 3.10+

**Impact:** `ImportError`/`AttributeError` the moment any 3.10 process
ever took an async timeout (every LLM call, every embedding call,
every health probe). The declared support matrix was a lie.

**Fix:** `stc_framework/resilience/timeout.py` now detects the Python
version and falls back to `asyncio.wait_for` + task-cancellation shim
on 3.10. `observability/health.py` also migrated to `wait_for`.

**Test:** `TestTimeoutPy310Compat`.

---

### S2 — Budget had a TOCTOU race under concurrent load

**Impact:** The old flow was `enforce(check observed)` → run LLM →
`record_cost`. Two concurrent requests from the same tenant that
would each fit individually but not together BOTH pass the check
before either records; the tenant exceeds their budget with no
rejection. In a high-QPS SaaS this is how the "$50k OpenAI bill
mystery" happens.

**Fix:** Added `TenantBudgetTracker.reserve` — atomic
`enforce + record` under the lock — and `settle` for post-hoc refund
/ top-up once the real cost is known. `STCSystem.aquery` now reserves
the per-task ceiling up front, settles with the real cost after, and
refunds on crash or input-rail block. Budget boundary tightened from
`>=` to `>` so the full allowance is usable.

**Test:** `TestBudgetConcurrency`.

---

### S3 — Flask shutdown timed out before the drain finished

**Impact:** `_SystemRunner.shutdown` submitted `astop()` with a 10 s
wait; `astop` itself defaults to 30 s drain timeout. During a rolling
deploy the Flask worker process would abort the drain at 10 s,
corrupting in-flight audit records and returning 5xx to clients that
would otherwise have completed.

**Fix:** `_SystemRunner.shutdown(drain_timeout)` now takes a timeout
and passes it to `astop`, waiting `drain_timeout + 5 s` for
completion. A SIGTERM/SIGINT handler is registered in `create_app` so
Kubernetes `preStop` → SIGTERM → clean drain works out of the box.

**Test:** `TestAdapterClose` (drain path exercised via astop).

---

### S4 — Adapter connections leaked on shutdown

**Impact:** `OllamaEmbeddings` opened an `httpx.AsyncClient` in its
`__init__` and only closed it if the caller explicitly called
`aclose`. Nothing in the pipeline called `aclose`. Over many
long-running processes this leaks sockets until the OS evicts the
process.

**Fix:** `STCSystem.astop` now invokes `aclose()` on every adapter
that exposes it (LLM, vector store, embeddings, prompt registry).
Failures in one adapter's close don't block the others.

**Test:** `TestAdapterClose`.

---

### S5 — Missing SIGTERM handler

**Impact:** Pods killed without graceful shutdown → in-flight audit
records lost mid-write (but hash chain survives due to prior work).
Clients received connection resets instead of completed responses.

**Fix:** `stc_framework.service.app.create_app` registers
SIGTERM/SIGINT handlers that call `runner.shutdown(drain_timeout=30)`.

**Test:** Indirectly via adapter-close tests; signal-path test is
platform-dependent and deliberately omitted.

---

### S6 — No per-tenant RPS rate limit

**Impact:** Budget capped *spend*, not *rate*. A tenant with a cheap
query loop could flood the system at arbitrary QPS and starve others
of bulkhead slots / audit writes / circuit-breaker capacity without
breaching cost limits.

**Fix:** `stc_framework.governance.rate_limit.TenantRateLimiter` —
token-bucket per tenant, bounded tenant set to avoid heap blow-up.
`STCSystem` checks it in `aquery` after degradation and before budget.
`STC_TENANT_RPS` env var (0 = disabled; the default). Rejections are
retryable → clients back off, unlike budget rejections.

**Test:** `TestRateLimiter`.

---

### S7 — No operator CLI for governance tasks

**Impact:** Responding to a GDPR Art. 17 request required writing
Python in a shell; verifying audit integrity after an incident
required the same. Runbooks couldn't be one-liners. Under incident
pressure this is a recipe for typos and mistakes.

**Fix:** `stc-governance` CLI:

```
stc-governance verify-chain <audit_dir>
stc-governance dsar <tenant> [--spec] [--output]
stc-governance erase <tenant> --yes
stc-governance retention
```

Registered as a `project.scripts` entry so it lands on `PATH` after
`pip install`.

**Test:** `TestGovernanceCLI`.

---

### S8 — Supply chain had zero enforcement

**Impact:** CI ran lint, mypy, tests — but never scanned for
vulnerable dependencies, never produced an SBOM, never checked for
committed secrets. A CVE in a transitive dep could ship to production
silently.

**Fix:** New `supply-chain` job in `.github/workflows/ci.yml`:
- `pip-audit` for Python CVEs.
- `cyclonedx-py` generates a CycloneDX SBOM artifact on every run.
- `git grep` secrets scan blocks obvious AWS / Slack / OpenAI /
  private-key patterns from landing in tracked files.

For production hardening, swap the regex scan for `gitleaks` or
`detect-secrets` — this commit lays the shape but keeps tooling
standard-library-only.

---

---

## Round 2 — Pre-deployment review for regulated environments

### Blockers (now fixed)

**R2-B1 — WORM-compatible audit backend**

`WORMAuditBackend` (`stc_framework.adapters.audit_backend.worm`) is
append-only, refuses `prune_before` / `erase_tenant` with
`ComplianceViolation`, writes a rotation-seal record every time a file
rolls over so the hash chain spans file boundaries, and is selected
via `STC_AUDIT_BACKEND=worm`. Under SEC 17a-4 this backend must be
paired with OS / cloud immutability (S3 Object Lock in compliance
mode, Linux `chattr +a`, Immudb, etc.) — the library provides the
shape, the infrastructure provides the enforcement.

**R2-B2 — HMAC-signed hash chain**

The audit chain is now HMAC-SHA256, not plain SHA-256. An attacker
with write access but no key cannot recompute `entry_hash` values that
verify. The key is read from `STC_AUDIT_HMAC_KEY` (base64, ≥16
bytes); in dev the system falls back to a per-process ephemeral key
with a warning. Every record carries a `key_id` so rotations are
traceable. Post-retention verification uses
`verify_chain(..., accept_unknown_genesis=True)`.

**R2-B3 — Ed25519 spec signature verification**

`stc_framework.spec.signing.verify_spec_signature` validates a
`.sig` sidecar file against the public key in `STC_SPEC_PUBLIC_KEY`.
In prod the verification is mandatory; in dev a missing signature is
tolerated, but a present-but-invalid signature still raises. For real
production use, prompt/spec updates should be signed from a hardware
token (Yubikey, sigstore, HSM) — the `sign_spec` helper exists only
for CI fixtures.

**R2-B4 — Strict prod mode enforced at `astart()`**

`STCSettings.env == "prod"` now enforces six fail-closed invariants:

1. `STC_AUDIT_HMAC_KEY` must be set (no ephemeral keys).
2. `STC_TOKENIZATION_STRICT=1` must be set.
3. `STC_LOG_CONTENT=false` — no request bodies in logs.
4. `STC_LOG_CONTENT=false` — content logging explicitly off.
5. `STC_LLM_ADAPTER != "mock"` — no accidental mock in prod.
6. Audit backend must be `WORMAuditBackend`.
7. Spec signature must verify.

Missing any invariant raises `STCError` at `astart()` so the
Kubernetes readiness probe fails and the pod never enters the pool.

**R2-B5 — Per-event-class retention policies**

`AuditSpec.retention_policies: RetentionPolicy` replaces the single
`retention_days` knob. Compliance-sensitive events
(`erasure`, `dsar_export`, `boundary_crossing`,
`data_sovereignty_violation`, `escalation_transition`) default to
6 years; chain-seal records (`audit_rotation_seal`,
`retention_prune_seal`) default to *forever*; the rest use the
spec-level default. `apply_retention` walks the policy table and only
deletes files when every class agrees the contents are expired — and
refuses to delete anything when a "forever" class is present.

### Hidden bugs (now fixed)

**R2-H1 — Idempotency cache cleared on erasure**

`governance.erase_tenant` now invokes
`system._idempotency.erase_tenant(tenant_id)`,
`system._budget.erase_tenant(tenant_id)`, and
`system._rate_limiter.erase_tenant(tenant_id)`. Previously-cached
`QueryResult` objects cannot resurface post-erasure, and the erasure
audit record includes counters for all three stores.

**R2-H2 — Retention chain seal**

`JSONLAuditBackend.prune_before` writes a `retention_prune_seal`
record before deleting files. The seal carries the hash of the last
pruned record so `verify_chain(..., accept_unknown_genesis=True)`
confirms the surviving chain is internally consistent.

**R2-H3 — Budget tracker with day buckets + monotonic-clock check**

`TenantBudgetTracker` aggregates costs into UTC day buckets (35-day
ring) rather than a linear sample list. `observed()` is now O(1) per
window regardless of request rate, and a wall-clock jump cannot
corrupt the window because each sample writes into today's bucket
keyed by calendar date. A monotonic-clock cross-check emits a warning
if wall time appears to move backwards between operations.

### Nits (now fixed)

- **R2-N1** — `reset_*_for_tests` moved into
  `stc_framework.testing`, which raises `RuntimeError` at call time if
  `STC_ENV=prod`. Production code grep-ing for the module catches the
  accidental test-hook import.
- **R2-N2** — covered by R2-H3 (rolling-sum day buckets).
- **R2-N3** — `MockLLMClient` now splits on `CONTEXT:` / `QUESTION:`
  and extracts numbers / citations only from the CONTEXT block. Every
  mock response is tagged `[mock-llm]` so audit reviewers cannot
  confuse a mock response with production.
- **R2-N4** — `STCSystem._run_pipeline` refactored to the standard
  4-space indent; the inner `async with self._inflight.track()` and
  `with bind_correlation(...)` stack is now a flat sequence rather
  than a visually-confusing 10-space hybrid.
- **R2-N5** — `STCSpec.rail_by_name` memoizes on first call.

### Additional hardening

- **Presidio warmup in `astart`** — `redact("warmup")` runs on first
  start so the first real query doesn't pay spaCy's cold-start cost.
- **Adapter `aclose()` plumbing** — `STCSystem.astop` gracefully closes
  every adapter that supports it.

---

## Tier 2 — Significant gaps that need fixing (roadmap)

### S9 — Global singletons cross-contaminate STCSystem instances

`_circuits` (resilience.circuit), `_STATE` (resilience.degradation),
`_metrics` (observability.metrics) are module-level singletons. Two
`STCSystem` instances in the same Python process share circuit state,
degradation state, and Prometheus metrics. This is fine for the
default deployment (one pod = one system) but breaks the moment a
multi-tenant SaaS tries to host multiple isolated `STCSystem`s per
worker.

**Proper fix:** thread these through a `SystemContext` DI object
instead of module globals. Estimated: ~1 day of refactor, breaking
change to test helpers, bumps to minor version.

**Workaround today:** one `STCSystem` per process; use horizontal
scaling for isolation.

---

### S10 — Streaming LLM responses not supported

`LLMClient.acompletion` returns a full `LLMResponse` at once. Every
enterprise chat UI expects token-by-token streaming. Without it,
first-token-latency for long responses is the full generation time.

**Proper fix:** add `LLMClient.astream(...)` → `AsyncIterator[LLMChunk]`
to the Protocol; add a streaming path in `StalwartAgent` that runs
output rails on the accumulated buffer; expose
`POST /v1/query?stream=true` returning text/event-stream.

Non-trivial — needs spec changes (how do hallucination rails work on
partial text?) and breaking-change consideration.

---

### S11 — No shadow-mode / canary deployment support

Operators can't ship a new prompt version to 10% of traffic for
comparison, can't run a new Critic ruleset in shadow mode before
enforcing. The Trainer can activate a new prompt version, but there's
no way to activate it for tenant `X ∈ Y`.

**Proper fix:** tenant-aware prompt/routing selection with
percentage sharding; `shadow` action that runs the rail but never
blocks (just records the would-have-blocked verdict to audit).

---

### S12 — No feature flags / kill switches

Cannot flip a specific validator off without editing the spec and
restarting. Incident response is harder than it should be.

**Proper fix:** env-var-overridable flags keyed by rail name and
persona (e.g. `STC_KILL_RAIL=numerical_accuracy` to disable in an
incident); audit all flag flips.

---

### S13 — No chaos / load test harness

No tests verify behavior under:
- adapter partial failure (25% of LLM calls error out),
- adapter slow (p99 = 10s),
- network partition between STCSystem and vector store,
- disk full on audit write,
- clock skew,
- sustained high load.

**Proper fix:** `tests/chaos/` + `tests/load/` directories; use
`respx` + `freezegun` + synthetic failure injection via adapter
wrappers; run in CI nightly (not per-PR) to keep the fast loop fast.

---

### S14 — No performance benchmarks

No `tests/benchmark/` with p50/p95 assertions. Cannot detect
performance regressions in PRs. A change that doubles per-query
memory allocations would pass review.

**Proper fix:** `pytest-benchmark` with baseline comparison;
benchmark fixtures for classify, retrieve (in-memory), reason (mock
LLM), full aquery.

---

### S15 — No API versioning strategy

Public types (`QueryResult`, `AuditRecord`, adapter Protocols) have
no `@stable` vs `@experimental` markers. A minor version bump could
break downstream callers. `py.typed` is present but no `.pyi` stubs
for async iterators.

**Proper fix:** adopt a `@public` / `@experimental` decorator
convention; document in `CONTRIBUTING.md`; add a
`tests/api_contract.py` that snapshots the public surface and fails
PRs that change it without a version bump.

---

### S16 — Config hot-reload absent

Rotating a prompt version, changing a rail threshold, or updating a
routing preference all require a process restart. Acceptable for
Kubernetes with rolling deploys, painful elsewhere.

**Proper fix:** optional `watchdog` observer on the spec file;
`STCSystem.areload(new_spec)` that atomically swaps the spec while
keeping in-flight queries running on the old one.

---

### S17 — No multi-region / active-active story

The audit log is local files, the history store is local SQLite,
token store is local. Zero support for deploying across regions with
synchronized state.

**Proper fix:** pluggable cloud backends (S3 for audit, Aurora for
history, AWS Secrets Manager for token store key). Not a library
concern today, but docs should be explicit about the limitation.

---

### S18 — LLM model-drift / output-fingerprint detection

Agent Lightning records traces but nothing detects when the LLM
provider silently rolls out a new model weight that changes output
distribution. An enterprise customer expects a regression alarm when
"gpt-4o-2024-05" quietly becomes "gpt-4o-2024-08".

**Proper fix:** rolling hash of response distributions per
`(model, prompt_version)` pair; alert on distribution shift.

---

### S19 — No Architecture Decision Records (ADRs)

Design choices — why LangGraph is optional, why we ship a mock LLM
default, why the audit chain is per-file not per-row — live only in
code review comments and chat.

**Proper fix:** `docs/adr/` directory with one markdown file per
decision following the Michael Nygard template.

---

### S20 — Silent-failure paths in observability

`AuditLogger._record_metric` swallows every exception to guarantee
audit never fails for a metrics reason — correct in principle, but
there's no alert on the swallowed failure. If Prometheus breaks,
dashboards go dark and nobody knows.

**Proper fix:** a `stc_observability_errors_total` counter that
increments when audit, tracing, or metric code itself throws.

---

## Tier 3 — Nice-to-have (tracked, not urgent)

- **Fuzz tests** on the regex surface (injection rules, PII patterns,
  number normalizer).
- **Mutation testing** (`mutmut`) to grade test quality.
- **OpenAPI spec** for the Flask service.
- **Devcontainer** / `docker-compose.dev.yml` for one-command local
  setup.
- **Reproducible builds** — pin every transitive dep via
  `requirements.lock`; verify builds are bit-identical.
- **Signed releases** — sigstore / cosign on every GitHub Release.
- **Multi-language notifier templates** for Slack / PagerDuty.
- **Request deduplication** at the HTTP layer (retryable POSTs
  without idempotency keys are still a risk).
- **Hedged requests** — fire two LLM calls in parallel and cancel
  the slower one; reduces p99 materially at ~2x cost.
- **Admission control** — reject requests when tail latency exceeds
  SLO rather than timing out every request.
- **Memory profiling** — a `tests/memory/` that asserts
  per-query allocations stay bounded.
- **i18n / encoding** — full Unicode edge-case tests for query text.
- **Timezone / DST** edge-case tests.
- **Legal hold** — a flag that suspends retention deletion for
  specific tenants under litigation hold.
- **Data portability format** — DSAR output in a machine-readable
  standard (CCPA-recommended JSON-LD, GDPR Art. 20 data portability).
- **Consent tracking** — per-tenant consent records referenced from
  every query audit (not every deployment needs this).
- **Cost attribution beyond USD** — GPU-minutes, carbon, latency
  budget; relevant for internal shared-cluster deployments.
- **Tenant tier quotas** — free/standard/premium with different
  budgets, RPS caps, model access.

---

## What this review explicitly does NOT claim

- **We have not performed a real security audit.** No pen test, no
  fuzzing campaign, no formal threat model. The defences in
  `SECURITY_AUDIT.md` are defence-in-depth, not proof of security.
- **We have not proved concurrency correctness.** No TLA+ spec, no
  Jepsen-style testing. The concurrency primitives are reasonable
  under review but not formally verified.
- **We have not load-tested at production scale.** The "millions of
  consumers" target in the original request is a design goal, not a
  measured fact. Actual capacity needs real measurement on the
  target hardware.
- **The regulatory crosswalk is informational.** It maps framework
  controls to regulation text, but compliance is the deployer's
  responsibility. An attorney and a DPO should sign off before
  production use.

---

## How to run the full audit battery

```bash
pip install -e ".[dev,service]"
pytest tests/unit/test_security.py     tests/unit/test_privacy.py       tests/unit/test_observability.py tests/unit/test_enterprise.py    tests/unit/test_staff_review.py  -v
```

All five suites must be green before a release. Additionally:

- `pip-audit --strict`
- `cyclonedx-py environment --output-file sbom.json`
- Manually inspect a sample of audit records with
  `stc-governance verify-chain <dir>` in staging.
- Load test with `locust` or equivalent against the Flask service.
