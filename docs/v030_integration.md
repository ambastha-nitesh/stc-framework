# v0.3.0 Integration Guide

How the new v0.3.0 subsystems plug into `STCSystem`. Each subsystem is
opt-in — none runs unless the operator explicitly wires it. The v0.2.0
hot path is unchanged, so zero-config deployments behave identically.

## TL;DR — what's new and where to reach it

| Subsystem | Import | Spec section |
|---|---|---|
| Data catalog | `stc_framework.governance.DataCatalog` | (programmatic) |
| Data lineage | `stc_framework.governance.LineageBuilder` / `LineageStore` | (programmatic) |
| Secure destruction | `stc_framework.governance.destroy_with_hold_check` | `audit.retention_policies` |
| Token/burst/cost controls | `stc_framework.governance.{TokenGovernor,BurstController,CostCircuitBreaker}` | `trainer.cost_thresholds` |
| Cost anomaly | `stc_framework.governance.CostAnomalyDetector` | (programmatic) |
| Risk register / KRI | `stc_framework.risk.{RiskRegister,KRIEngine}` | `risk_appetite` |
| Risk-adjusted optimizer | `stc_framework.risk.RiskAdjustedOptimizer` | `risk_appetite.decision_weights` |
| FINRA Rule 2210 | `stc_framework.compliance.Rule2210Engine` | `compliance_profile` |
| Reg BI suitability | `stc_framework.compliance.RegBICheckpoint` | `compliance_profile` |
| NYDFS 72-hour | `stc_framework.compliance.NYDFSNotificationEngine` | `compliance_profile` |
| Part 500 certification | `stc_framework.compliance.Part500CertificationAssembler` | `compliance_profile` |
| Bias & fairness | `stc_framework.compliance.BiasFairnessMonitor` | `compliance_profile` |
| Legal hold | `stc_framework.compliance.LegalHoldManager` | `compliance_profile.legal_hold_enabled` |
| Sovereignty | `stc_framework.compliance.sovereignty.*` | `sovereignty` |
| Threat detection | `stc_framework.security.ThreatDetectionManager` | `threat_detection` |
| Pen testing | `stc_framework.security.PenTestRunner` | (programmatic / CI) |
| Orchestration | `stc_framework.orchestration.WorkflowOrchestrator` | `orchestration` |
| Session state | `stc_framework.infrastructure.SessionManager` | `session_state` |
| Perf testing | `stc_framework.infrastructure.PerformanceTestRunner` | `perf` |

All pluggable state routes through
`stc_framework.infrastructure.KeyValueStore`. The shipped default is
`InMemoryStore`; a Redis implementation arrives in v0.3.1.

---

## Patterns

### Enable FINRA 2210 enforcement on every output

The compliance engine is most useful as a Critic output rail. Wire it
via the `ComplianceRailBridge`:

```python
from stc_framework.compliance.rule_2210 import Rule2210Engine
from stc_framework.critic.validators.compliance_rail import ComplianceRailBridge
from stc_framework.infrastructure.store import InMemoryStore

engine = Rule2210Engine(store=InMemoryStore(), enforce_critical=False)
bridge = ComplianceRailBridge(engine=engine)

# After system.astart():
system.critic._rail_runner.register(bridge)  # internal API — pending a public register
```

Then declare the rail in the spec:

```yaml
critic:
  guardrails:
    output_rails:
      - name: compliance_finra_2210
        severity: critical
        action: block
```

Critical violations now produce a blocked `GovernanceVerdict` instead
of raising. Lower-severity findings route to the principal-approval
queue (accessible via `engine.approval_queue`).

### Wire a risk-adjusted optimizer into Trainer decisions

```python
from stc_framework.risk import (
    KRIEngine, RiskAdjustedOptimizer,
    ProvenanceEvaluator, SovereigntyEvaluator,
    ConcentrationEvaluator, KRIEvaluator,
    OptimizationCandidate, OriginRisk,
)

kri = KRIEngine(store=store)
await kri.bootstrap_defaults()
optimizer = RiskAdjustedOptimizer(
    provenance=ProvenanceEvaluator(allowed_origin_risks={OriginRisk.TRUSTED.value, "cautious"}),
    sovereignty=SovereigntyEvaluator(allowed_jurisdictions={"US"}),
    concentration=ConcentrationEvaluator(max_share=0.75),
    kri=KRIEvaluator(kri_engine=kri),
)

# Inside the Trainer's routing controller:
candidates = [
    OptimizationCandidate(candidate_id="gpt-4", accuracy_score=0.93, cost_score=0.30,
                          metadata={"origin_risk": "trusted", "jurisdiction": "US"}),
    OptimizationCandidate(candidate_id="mistral-large", accuracy_score=0.88, cost_score=0.70,
                          metadata={"origin_risk": "cautious", "jurisdiction": "EU"}),
]
decision = await optimizer.optimize("llm_route", candidates, data_tier="internal")
```

On an all-vetoed case the optimizer raises `RiskOptimizerVeto`; callers
typically fall back to the v0.2.0 spec routing order in that branch.

### Register a honey token and route threat alerts

```python
from stc_framework.security.threat_detection import ThreatDetectionManager

threats = ThreatDetectionManager(audit=system._audit)
threats.deception.register_honey_token("STC_TOK_honeypot-2026")

# In the Stalwart's detokenization path, after surrogate substitution:
for token in surrogate_tokens_in_output:
    threats.honey_token_used(token)  # raises HoneyTokenTriggered
```

The manager automatically pushes `DegradationState` to DEGRADED when a
critical threat fires. Callers that want additional escalation (page an
on-call SOC engineer) subscribe to `DegradationState` transitions.

### Record end-to-end lineage for every request

```python
from stc_framework.governance.lineage import (
    LineageBuilder, LineageStore, SourceDocumentNode,
    EmbeddingNode, GenerationNode, ResponseNode,
)

lineage_store = LineageStore(store=store, audit=audit_logger)

# Inside your request handler (pseudo-code around the existing pipeline):
trace_id = current_correlation()["trace_id"]
builder = LineageBuilder(trace_id, tenant_id=tenant_id, session_id=session_id)

# ...after retrieval:
builder.add_source_documents([SourceDocumentNode(doc_id=d) for d in retrieved_ids])
builder.add_embedding(EmbeddingNode(embedder_id="bge-large", vector_size=1024))

# ...after LLM call:
builder.add_generation(GenerationNode(
    model_id=llm_response.model,
    input_tokens=llm_response.prompt_tokens,
    output_tokens=llm_response.completion_tokens,
    cost_usd=llm_response.cost,
))

# ...after Critic:
builder.add_response(ResponseNode(char_count=len(final_output)))

record = builder.build()
await lineage_store.store(record)
```

Auditors later run `lineage_store.impact_analysis(doc_id)` to list
every response that used a specific document — essential for DSAR
erasure planning.

### Block destruction during litigation

```python
from stc_framework.compliance.legal_hold import LegalHold, LegalHoldManager

holds = LegalHoldManager(store=store, audit=audit_logger)
await holds.issue(LegalHold(
    hold_id="matter-2026-001",
    matter_id="Acme v. STC",
    tenant_ids=["acme"],
    keywords=["contract", "email"],
    issued_by="counsel@company.com",
    reason="Active discovery",
))

# The retention sweep consults the manager before destroying anything:
from stc_framework.governance.destruction import (
    DestructionMethod, destroy_with_hold_check, overwrite_file,
)

async def _destroy() -> bool:
    return overwrite_file(artifact_path)

await destroy_with_hold_check(
    data_store="filesystem",
    artifact=str(artifact_path),
    method=DestructionMethod.SECURE_OVERWRITE,
    destroy_fn=_destroy,
    legal_hold=holds,  # implements LegalHoldChecker
    tenant_id="acme",
)
# Raises LegalHoldActive if a matching hold is in force.
```

### Opt into a blanket-scope hold explicitly

A hold with `keywords=[]` matches no artifacts by default (this was
hardened by v0.3.0 staff-review finding R7). To freeze the entire
deployment — e.g. during a maintenance window — set `scope_all=True`:

```python
await holds.issue(LegalHold(
    hold_id="maint-2026-02",
    scope_all=True,
    reason="Maintenance freeze",
    issued_by="ops@company.com",
))
```

### Use the pluggable session state

```python
from stc_framework.infrastructure import SessionManager, InMemoryStore

sessions = SessionManager(InMemoryStore(), default_ttl_seconds=3600, audit=audit_logger)
await sessions.create_session("sess-42", tenant_id="acme", data_tier="internal")
await sessions.save_context("sess-42", {"turns": [...]})
ctx = await sessions.load_context("sess-42")  # raises SessionExpired if past TTL

# Atomic cost accumulation (stored in micro-dollars internally):
total_today = await sessions.increment_cost("stalwart", usd=0.032, tenant_id="acme")
```

When the Redis backend lands in v0.3.1, swapping the store is the only
change — the `SessionManager` API is identical.

### Run a load test with SLO validation

```python
from stc_framework.infrastructure.perf_testing import (
    LoadConfig, LoadProfile, PerformanceTestRunner,
)

async def probe() -> None:
    await system.aquery("What is the Q3 revenue?", tenant_id="test-tenant")

runner = PerformanceTestRunner(probe_fn=probe, store=store, audit=audit_logger)
result = await runner.run_load_test(
    LoadConfig(profile=LoadProfile.PEAK, rps=50.0, duration_seconds=60.0, ramp_seconds=10.0)
)
regression = await runner.regression_check(result)
```

Violations are emitted to the audit chain (`SLO_VIOLATION`) and
Prometheus (`stc_slo_violations_total`).

---

## Metrics reference (v0.3.0 additions)

Every metric is registered on the default `STCMetrics` container and
uses the `stc_` prefix:

| Metric | Type | Labels |
|---|---|---|
| `stc_compliance_checks_total` | Counter | `rule`, `outcome` |
| `stc_compliance_violations_total` | Counter | `rule`, `severity` |
| `stc_risk_score` | Gauge | `category`, `tenant` |
| `stc_kri_status` | Gauge | `kri_id` |
| `stc_threats_detected_total` | Counter | `threat_type`, `severity` |
| `stc_ip_blocks_total` | Counter | — |
| `stc_workflow_duration_ms` | Histogram | `workflow_type` |
| `stc_workflow_tasks_total` | Counter | `status` |
| `stc_session_active` | Gauge | `backend` |
| `stc_session_cost_usd_total` | Counter | `tenant` |
| `stc_slo_violations_total` | Counter | `slo_name` |
| `stc_asset_quality_score` | Gauge | `asset_type` |

Safe emission is via `stc_framework._internal.metrics_safe.{safe_inc,safe_set,safe_observe}`;
these catch label-mismatch errors, log at WARNING, and never crash
application code (v0.3.0 staff-review finding R8).

---

## Error taxonomy reference

v0.3.0 adds these `STCError` subclasses (HTTP mappings via `http_status_for`):

* Compliance: `ComplianceViolation` (422), `FINRARuleViolation` (422),
  `RegBIUnsuitable` (422), `DisclosureMissing` (422),
  `LegalHoldActive` (423).
* Risk: `RiskAssessmentError` (500), `KRIRedVeto` (503),
  `RiskAppetiteBreach` (403), `RiskOptimizerVeto` (503).
* Threats: `ThreatDetected` (403), `DDoSDetected` (429),
  `HoneyTokenTriggered` (403), `BehavioralAnomalyDetected` (403).
* Orchestration: `OrchestrationError` (500),
  `WorkflowBudgetExhausted` (402), `StalwartDispatchFailed` (503),
  `WorkflowCriticRejected` (502).
* Session: `SessionStateError` (500), `SessionExpired` (440),
  `SessionBackendUnavailable` (503).

---

## Deferred to v0.3.1

- Redis implementation of `KeyValueStore` (under the `[session]` extra).
- LangGraph `StateGraph` backend for `WorkflowOrchestrator`.
- Direct wiring of these subsystems into `STCSystem.aquery` step order
  (programmatic wiring works today; the default factory path is v0.3.1).
- Public `Critic.register_validator` API (today the rails register via
  the internal `_rail_runner` hook).
