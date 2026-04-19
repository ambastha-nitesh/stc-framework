# STC Framework v0.3.0 — Staff-Level Code Review

This document captures the staff-engineer review of the v0.3.0 capability-
completion release (PR #2). Every Phase 0–5 module was walked with the
same skepticism applied to `docs/security/STAFF_REVIEW.md`. Findings
are grouped by tier; each tier-1 item has a fix in this commit and a
regression test in `tests/unit/test_v030_staff_review.py`.

The v0.2.0 review found 7 + 13 issues across two rounds; this review
surfaces 8 tier-1 bugs, 4 tier-2 items, and 6 tier-3 roadmap items.

---

## Tier 1 — Bugs fixed in this commit

### R1 — `InMemoryStore.erase_tenant` matched tenant IDs as substrings

**Impact:** `erase_tenant("t")` matched `"risk:t1:r1"` because the
contract was "any key containing `:{tenant_id}:`" — a legitimate
tenant ID that is a prefix of another tenant's ID would cause
cross-tenant deletion during a DSAR erasure sweep. For a
multi-tenant deployment with short ids (`t1`, `t2`, …) or sequential
ids (`cust-1`, `cust-10`), an erasure for the short one wiped the
longer one.

**Fix:** `InMemoryStore.erase_tenant` now split-scans the key on
`":"` and matches tenant id as an **exact segment**, not a substring.
All subsystems that tenant-scope their keys (`risk:`, `session:`,
`compliance:consent:`) are compatible — they all already use
`{prefix}:{tenant_id}:{rest}`. The Protocol docstring documents the
required key scheme explicitly.

**Test:** `TestR1TenantIDSegmentMatch`.

---

### R2 — `LineageStore._append_index` had a read-modify-write race

**Impact:** Two concurrent `store()` calls for lineage records
referencing the same document both `get()` the current index list,
append their own id, and `set()`. The second write clobbers the
first. In production this silently loses lineage records from the
document index — so `impact_analysis(doc_id)` returns an
undercount, and DSAR erasure sweeps miss affected responses.

**Fix:** `LineageStore` now owns an `asyncio.Lock` guarding all
index mutations. `_append_index` acquires it, does the
read-append-write, releases. The primary record write is outside
the lock (it's keyed by lineage id, no contention).

**Test:** `TestR2LineageIndexConcurrency`.

---

### R3 — `threat_detection` used deprecated `asyncio.get_event_loop()`

**Impact:** `ThreatDetectionManager._record` called
`asyncio.get_event_loop().create_task(...)` to fire-and-forget the
audit emit. On Python 3.10+ `get_event_loop()` emits a
`DeprecationWarning` when there is no running loop and will raise in
3.12+ . Synchronous test paths that feed threat records (e.g. a
harness that calls `honey_token_used()` outside `asyncio.run`)
tripped this; production code running under uvicorn / asyncio is
fine for now but would break on the 3.12 runtime bump.

**Fix:** Switched to `asyncio.get_running_loop()` inside a
`try/except RuntimeError`. If no loop is running the audit emit is
dropped silently (matches the prior best-effort contract).

**Test:** `TestR3ThreatDetectionNoLoopNoCrash`.

---

### R4 — `KRIEngine.register` accepted inconsistent thresholds

**Impact:** Nothing checked that `amber`/`red` made sense for the
declared `direction`. A typo like
`KRIDefinition(direction="higher_is_worse", amber=10, red=5)` would
silently classify a measurement of `8` as GREEN (below amber 10),
invert the severity, and never fire the escalate-on-RED hook. A
silent failure mode for a regulatory-facing risk layer.

**Fix:** `KRIEngine.register` validates the threshold ordering
against `direction`. `higher_is_worse` requires `amber < red`;
`lower_is_worse` requires `amber > red`. Violations raise
`ValueError` at registration so the failure surfaces at boot, not
at the first RED measurement that didn't happen.

**Test:** `TestR4KRIThresholdValidation`.

---

### R5 — `_internal.Pattern.metadata` defaulted to `None`

**Impact:** The dataclass declared `metadata: dict[str, Any] = None`
with a `# type: ignore[assignment]`. Any caller who did
`pattern.metadata.get(...)` without a None-check raised
`AttributeError`. Also, because mypy was silenced, the type system
could not catch it. `pen_testing.py` does
`pattern.metadata.get("category", ...)` and would raise for any
pattern without an explicit `metadata:` entry in the YAML.

**Fix:** `metadata: dict[str, Any] = field(default_factory=dict)`.
Removed the `type: ignore`.

**Test:** `TestR5PatternMetadataDefault`.

---

### R6 — Catalog `asdict_safe` had a fallback branch for an unreachable case

**Impact:** `catalog.asdict_safe` wrapped its result in
`{"value": result}` if `_asdict_recursive` returned a non-dict.
Every caller passed a dataclass; the branch was unreachable and
actively misleading — the payload shape in the store would differ
from every other branch if the branch ever ran. This is the kind of
defensive code that masks bugs rather than fixing them.

**Fix:** Deleted the branch. Tightened the type signature to
accept only the three known dataclasses (`DocumentAsset`,
`ModelAsset`, `PromptAsset`, `QualityDimensions`) and return
`dict[str, Any]` directly.

**Test:** `TestR6CatalogSerializerStrictInputs`.

---

### R7 — `LegalHoldManager` treated `keywords=[]` as a blanket hold

**Impact:** `LegalHold(hold_id="h", keywords=[])` matched every
artifact — the `if hold.keywords:` branch was skipped entirely so
scope defaulted to "match all." This might be the intended semantic
for a maintenance-window hold, but nothing in the docstring said so,
no test covered it, and a novice could accidentally freeze every
destruction across the entire deployment by omitting `keywords`.

**Fix:** Split the two semantics explicitly. A new
`LegalHold.scope_all: bool = False` flag must be set True for
blanket holds. `keywords=[]` without `scope_all` now matches nothing
(the default is "scope says no artifacts match → hold does not
apply"). The docstring explicitly names both semantics.

**Test:** `TestR7LegalHoldExplicitScope`.

---

### R8 — Bare `except Exception` masked metric-label typos

**Impact:** Every metric emission block in v0.3.0 was wrapped in
`try: ... except Exception: pass`. The intent — don't crash
application code if Prometheus is unhappy — is correct, but the
implementation hides real bugs (wrong label names, wrong metric
shape). A dev would never see the `ValueError: Incorrect label
names` that Prometheus throws and could merge code that silently
never increments.

**Fix:** Introduced `stc_framework._internal.metrics_safe.safe_inc`
/ `safe_set` helpers that catch **only** the specific exception
classes Prometheus raises (`ValueError` for label mismatches) and
log the failure via structlog at `WARNING`. Application code still
doesn't crash, but the failure is visible in logs and discoverable
in tests. All v0.3.0 modules refactored to use the helper.

**Test:** `TestR8MetricSafeEmitLogsOnFailure`.

---

## Tier 2 — Fixed this commit (not strictly bugs, but caught by review)

### R9 — Missing Critic rail bridges

**Gap:** The v0.3.0 plan called for
`critic/validators/compliance_rail.py`, `bias_rail.py`,
`sovereignty_rail.py` to bridge the compliance engines into the
Critic output-rail surface. They were never written. Without them,
a caller who wants FINRA 2210 enforced on every response has to
invoke `Rule2210Engine.review` manually — the Critic's declarative
rail config does not reach the new engines.

**Fix:** Added the three validators. Each implements the Critic
`Validator` Protocol (``rail_name``, ``severity``, ``avalidate``)
and delegates to the corresponding engine. Callers declare the rail
name in the spec's `critic.guardrails.output_rails` and the engine
fires as part of the standard Critic pipeline.

**Test:** `TestR9CriticRailBridges`.

---

### R10 — No integration test for audit chain with new v0.3.0 events

**Gap:** v0.3.0 emits 30 new canonical `AuditEvent` values. The
v0.2.0 HMAC audit chain verifier (`observability.audit.verify_chain`)
should accept them identically to the existing events, but that
assumption was never tested.

**Fix:** Added an integration test that runs a small workflow
through v0.3.0 subsystems (compliance check, risk escalation, KRI
record, threat detection), appends the emitted records to a
`JSONLAuditBackend`, rotates the file, and calls `verify_chain`.
Any chain breakage shows up immediately.

**Test:** `TestR10V030AuditChainIntegrity`.

---

### R11 — `PenTestRunner` iterated the catalog twice

**Gap:** The original implementation called `catalog.scan("")` +
`[catalog.get(name) for name in catalog.names()]` and deduped
afterward. Correct outputs, wasteful code, misleading for a
reviewer. A reviewer would wonder why the scan-with-empty-string
was there at all (it never matches).

**Fix:** Replaced with a single
`[catalog.get(n) for n in catalog.names()]` pass. No dedup needed.

**Test:** covered by existing `test_pen_testing.py::test_runner_blocked_defences_produce_fail_attack`.

---

### R12 — `WorkflowOrchestrator` mutated state from inside the dispatcher closure

**Gap:** The inner `dispatcher` coroutine mutated
`state.results` and `state.total_cost_usd` without a lock. The
`SimulationEngine` runs tasks sequentially today so this is safe,
but the plan calls for a LangGraph backend in v0.3.1 that uses the
Send API for parallel fan-out. Shipping this closure structure
guarantees a race the day LangGraph lands.

**Fix:** Moved the state mutations behind an `asyncio.Lock` held by
the orchestrator. The additional contention is negligible (one lock
acquire per task result) and the code is ready for parallel
dispatch without a follow-up refactor.

**Test:** `TestR12OrchestratorConcurrentDispatch`.

---

## Tier 3 — Roadmap (not addressed in v0.3.0)

### R13 — `SessionManager` cost counter is daily-bucketed but never swept

Operators who run for more than 48 hours without a retention pass
accumulate `cost:{date}:{persona}` keys forever. Each one expires at
48h via TTL (see `increment_cost`), so the leak self-heals, but a
caller expecting to read yesterday's total will see 0 after the TTL.
Document this semantics; consider an explicit `sweep_cost_counters`
API that emits the daily total to audit before it expires.

### R14 — `RiskAdjustedOptimizer` does not surface evaluator timing

Each evaluator is sync except KRI. With N candidates × 4 evaluators
the wall-clock cost adds up; we have no metric for it. Add
per-evaluator histograms in v0.3.1.

### R15 — `workflow_engine` lacks durable checkpointing

`WorkflowOrchestrator` persists the final state to the store but not
intermediate state. A crash mid-workflow loses everything the
completed tasks produced. The LangGraph `StateGraph` wrapper in
v0.3.1 should enable checkpoint-per-task.

### R16 — `threat_detection.EdgeRateLimiter` is process-local

A fleet of workers behind a load balancer each track their own
per-IP windows. A distributed attacker spraying across pods passes
every individual worker's limit while the aggregate is N× over.
Document as a v0.3.1 item; the fix is a Redis-backed
`RollingWindowCounter` under the `[session]` extra.

### R17 — `Part500CertificationAssembler` has no retention

Evidence records live forever in the store. Regulators expect 6-year
retention on certifications; the assembler should tag records with a
retention class and the Phase-1 retention sweep should honour it.

### R18 — `BiasFairnessMonitor` has no windowed aggregation

`evaluate_fairness()` averages over all-time scores. A pattern that
starts good and drifts is not distinguishable from a pattern that
has always been bad-but-steady. Add a sliding-window `evaluate_fairness(window=timedelta(days=7))` in v0.3.1.

---

## Documentation gaps addressed in this commit

Beyond the code fixes, this commit adds:

- `docs/v030_integration.md` — how each v0.3.0 subsystem plugs into
  `STCSystem`, with code snippets for the common patterns (enable
  FINRA enforcement, wire a risk optimizer into Trainer, register a
  honey token).
- README v0.3.0 capability section — short user-facing summary that
  points to the integration doc for details.
- `experimental/README.md` — already updated in the Phase 6 commit;
  verified still accurate.

---

## Review sign-off

Every Tier-1 item in this document is fixed in this commit and has a
regression test. Tier-2 items 9–12 are also resolved. Tier-3 items are
carried to the v0.3.1 backlog.
