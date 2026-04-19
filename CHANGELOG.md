# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - Unreleased — capability completion

Ports every module previously parked in ``experimental/`` into the
supported ``src/stc_framework/`` package at the v0.2.0 quality bar
(async-first, typed, tested, observability-integrated). No hot-path
behaviour change for v0.2.0 workloads — every new subsystem is
opt-in through its own spec section (all default to disabled).

### Added — foundations (Phase 0)

- ``errors.py`` extensions: ``ComplianceViolation`` / ``FINRARuleViolation`` /
  ``RegBIUnsuitable`` / ``DisclosureMissing`` / ``LegalHoldActive``;
  ``RiskAssessmentError`` / ``KRIRedVeto`` / ``RiskAppetiteBreach`` /
  ``RiskOptimizerVeto``; ``ThreatDetected`` / ``DDoSDetected`` /
  ``HoneyTokenTriggered`` / ``BehavioralAnomalyDetected``;
  ``OrchestrationError`` / ``WorkflowBudgetExhausted`` /
  ``StalwartDispatchFailed`` / ``WorkflowCriticRejected``;
  ``SessionStateError`` / ``SessionExpired`` / ``SessionBackendUnavailable``.
  HTTP status-code mappings extended (423 Locked for legal hold, 440 for
  session expiry, etc.).
- ``AuditEvent`` extended with 30 new canonical event names spanning
  compliance, risk, threats, orchestration, catalog/lineage, and
  session/perf.
- ``STCMetrics`` extended with 12 new Prometheus metrics:
  ``stc_compliance_checks_total``, ``stc_compliance_violations_total``,
  ``stc_risk_score``, ``stc_kri_status``, ``stc_threats_detected_total``,
  ``stc_ip_blocks_total``, ``stc_workflow_duration_ms``,
  ``stc_workflow_tasks_total``, ``stc_session_active``,
  ``stc_session_cost_usd_total``, ``stc_slo_violations_total``,
  ``stc_asset_quality_score``.
- ``spec.models`` extended with ``CompliancePolicySpec``,
  ``SovereigntySpec``, ``RiskAppetiteSpec``, ``OrchestrationSpec``,
  ``ThreatDetectionSpec``, ``SessionStateSpec``, ``PerfSpec``. All
  optional; pre-v0.3.0 specs load unchanged.
- ``stc_framework._internal``: shared helpers — ``StatefulRecord``
  transition-logged state machine, ``ThresholdAlerter`` with
  GREEN/AMBER/RED hysteresis, ``WeightedScore`` + EEOC 4/5ths
  fairness ratio, YAML-backed ``PatternCatalog`` loader, ``TTL``
  deadline arithmetic.
- ``stc_framework.infrastructure.store``: ``KeyValueStore`` async
  Protocol with an in-memory default. Phase-1..5 subsystems route all
  persistent state through this so Redis (or any backend) can be swapped
  in without touching subsystem code.

### Added — governance (Phase 1)

- ``governance/catalog.py``: ``DataCatalog`` — six-dimension weighted
  quality scoring (accuracy-dominant), document/model/prompt registries,
  freshness-SLA sweep with auto-STALE transitions, quality-threshold
  auto-quarantine.
- ``governance/lineage.py``: ``LineageBuilder`` + ``LineageStore`` —
  incremental request-lineage graph (sources → embedding → retrieval →
  context → generation → validation → response). ``lineage_id`` is the
  OTel trace_id. Indexes by document/model/session; ``impact_analysis``
  for DSAR blast-radius queries.
- ``governance/destruction.py``: ``SecureDestruction`` utilities — DoD-style
  three-pass overwrite with cryptographic random on the final pass,
  ``crypto_erase``, ``verify_destruction``. ``destroy_with_hold_check``
  consults the Phase-3 ``LegalHoldChecker`` and emits
  ``DESTRUCTION_BLOCKED_BY_HOLD`` when denied.
- ``governance/budget_controls.py``: ``TokenGovernor`` (input/output
  caps + per-persona daily quota), ``BurstController`` (per-workflow
  LLM-call cap — catches runaway loops), ``CostCircuitBreaker``
  (five-band ladder normal → warn → throttle → pause → halt).
- ``governance/anomaly.py``: ``CostAnomalyDetector`` — rolling-mean
  per-model cost spike detector built on ``ThresholdAlerter``.

### Added — risk (Phase 2)

- ``risk/register.py``: ``RiskRegister`` — ISO 31000 lifecycle
  (identified → assessed → treatment_planned → accepted → monitoring →
  closed/escalated) with 5x5 likelihood-by-impact matrix and declared
  ``RISK_TRANSITIONS`` table. Inherent vs residual rating; heat map;
  full transition history.
- ``risk/kri.py``: ``KRIEngine`` with a 12-indicator default catalog
  (accuracy, hallucination rate, PII leak, sovereignty violations,
  budget saturation, latency p95, availability, guardrail failure rate,
  critic escalation rate, queue depth, vendor concentration, model
  drift). GREEN/AMBER/RED classification; RED transitions
  auto-escalate linked risks via caller callback.
- ``risk/optimizer.py``: ``RiskAdjustedOptimizer`` — four evaluators
  (provenance, sovereignty, vendor concentration, KRI) with
  ``VetoReason`` enum. Composite scoring = accuracy·w_a + cost·w_c +
  (1−risk)·w_r with configurable weights. All-vetoed raises
  ``RiskOptimizerVeto``.

### Added — compliance (Phase 3)

- ``compliance/patterns.py`` + ``compliance/data/*.yaml``: YAML-backed
  FINRA violation phrases + IP trademark catalogs. Legal teams update
  YAML directly.
- ``compliance/rule_2210.py``: ``Rule2210Engine`` with pattern detection,
  fair-balance scoring (``min(pos,risk) / max(pos,risk)``), disclosure
  verification, and a principal-approval queue for retail
  communications. Critical violations raise ``FINRARuleViolation``.
- ``compliance/reg_bi.py``: ``RegBICheckpoint`` — product-class risk
  detection against a ``CustomerProfile``.
- ``compliance/nydfs_notification.py``: ``NYDFSNotificationEngine`` —
  72-hour deadline tracker with AMBER at <24h remaining, RED at <4h,
  OVERDUE at 0.
- ``compliance/part_500_cert.py``: Evidence + gap assembler across the
  17 NYDFS Part 500 sections.
- ``compliance/bias_fairness.py``: EEOC 4/5ths disparate-impact monitor
  across demographic groups.
- ``compliance/ip_risk.py``: Pattern-catalog IP infringement scanner.
- ``compliance/transparency.py``: Idempotent disclosure stamping +
  per-customer consent registry.
- ``compliance/privilege_routing.py``: Attorney-client privilege
  keyword detector that forces ``local_only`` routing.
- ``compliance/fiduciary.py``: Per-tier model-usage fairness detector.
- ``compliance/legal_hold.py``: ``LegalHoldManager`` implementing the
  ``LegalHoldChecker`` protocol — destruction sweeps honour active
  holds automatically.
- ``compliance/explainability.py``: Seven-step narrative generator
  over a sealed ``LineageRecord``.
- ``compliance/sovereignty/``: ``ModelOriginPolicy`` (geopolitical
  risk), ``QueryPatternProtector`` (per-provider entity-concentration
  detector), ``StateComplianceMatrix`` (CO/CA/TX/IL/NY/UT extensible),
  ``InferenceJurisdictionEnforcer`` (FIPS-required-for-restricted).

### Added — security + orchestration (Phase 4)

- ``security/patterns.py`` + ``security/data/*.yaml``: Shared threat
  pattern + pen-test payload catalogs with MITRE ATLAS + OWASP LLM
  Top 10 metadata.
- ``security/threat_detection.py``: ``ThreatDetectionManager`` +
  ``EdgeRateLimiter`` (per-minute / per-hour / cost-exhaustion windows
  + IP blocklist), ``BehavioralAnalyzer`` (per-session trajectory),
  ``DeceptionEngine`` (honey docs/tokens/canaries). Critical alerts
  push ``DegradationState`` → DEGRADED automatically.
- ``security/pen_testing.py``: ``PenTestRunner`` producing MITRE/OWASP
  -tagged ``PenTestResult`` records with compliance-ready
  ``summarise()`` output.
- ``orchestration/registry.py``: ``StalwartRegistry`` with capability-tag
  lookup picking lowest-cost-weight match.
- ``orchestration/simulation.py``: Dependency-resolving task runner —
  propagates typed ``OrchestrationError`` subclasses to callers while
  capturing generic probe failures per ``fail_fast`` policy.
- ``orchestration/workflow.py``: ``WorkflowOrchestrator`` wiring
  registry + simulation + ``BurstController`` + cost cap + audit +
  store. Budget cap raises ``WorkflowBudgetExhausted``.

### Added — infrastructure (Phase 5)

- ``infrastructure/session_state.py``: ``SessionManager`` over
  ``KeyValueStore``. Key namespaces match experimental prototype so
  dashboards keep working. Cost stored in micro-dollars for atomic
  incr. ``assert_active`` raises ``SessionExpired``.
- ``infrastructure/perf_testing.py``: ``PerformanceTestRunner`` —
  four ``LoadProfile`` levels (baseline / peak / stress / soak),
  p50/p95/p99 + error-rate + RPS summary, ``validate_slos`` with
  direction-aware comparison, ``regression_check`` vs. the previous
  stored run, pure-function ``capacity_model`` headroom calculator.

### Changed

- ``pyproject.toml`` bundles ``compliance/data/*.yaml`` and
  ``security/data/*.yaml`` as package data so wheel installs carry
  the default catalogs.

### Testing

- 155 new tests across unit + contract suites (55 Phase 0 + 45 Phase 1
  + 25 Phase 2 + 42 Phase 3 + 23 Phase 4 + 20 Phase 5). Contract suite
  for ``KeyValueStore`` is parametrised over implementations so a
  future ``RedisStore`` slots in without duplicating test bodies.

### Not in this release (deferred to v0.3.1+)

- Direct integration of compliance / threat-detection / risk-optimizer
  hooks into ``STCSystem.aquery`` execution order. Subsystems are
  importable and fully tested; integrating them into the hot path
  requires cross-subsystem tests out of scope for v0.3.0.
- Redis backend implementation of ``KeyValueStore``. Protocol + contract
  tests are ready; the implementation ships behind a ``[session]`` extra
  in v0.3.1.
- LangGraph ``StateGraph`` backend for ``WorkflowOrchestrator``
  (pure-Python ``SimulationEngine`` ships in v0.3.0; LangGraph wrapper
  is a v0.3.1 addition).

## [0.2.0] - Unreleased

### Added

- **Package restructure** under `src/stc_framework/` with a `pyproject.toml`
  and semantic extras (`[presidio]`, `[qdrant]`, `[litellm]`, `[service]`, ...).
- **Async-first pipeline** for Sentinel gateway, Stalwart retrieval/embedding,
  and Critic rails; sync facade preserved on `STCSystem.query`.
- **Typed error taxonomy** (`stc_framework.errors`) rooted at `STCError`,
  propagated through resilience primitives and the Flask service layer.
- **Resilience primitives** in `stc_framework.resilience`: retries with
  full-jitter exponential backoff, per-downstream circuit breakers, async
  timeouts, bulkheads (asyncio semaphores), declarative fallback chains, and
  a global `DegradationState` state machine.
- **Structured logging** with structlog, correlation IDs via `ContextVar`,
  OpenTelemetry trace-context binding, and a PII-safe field filter.
- **Observability**: OTel tracing with optional OTLP export, Prometheus
  metrics (`stc_queries_total`, `stc_latency_ms`, `stc_guardrail_failures_total`,
  `stc_circuit_breaker_state`, `stc_escalation_level`, `stc_cost_usd_total`),
  and an append-only audit log with optional parquet export.
- **Adapter layer** with `Protocol` interfaces and working defaults for every
  external integration: LLM (mock/litellm), vector store (in-memory/qdrant),
  embeddings (hash/ollama/openai), prompts (file/langfuse), guardrails
  (regex/nemo/guardrails-ai), audit backends (jsonl/parquet/phoenix), and
  Agent Lightning.
- **Surrogate tokenization** in `sentinel.tokenization` with a reversible
  HMAC token scheme and an AES-GCM-encrypted local token store.
- **Virtual key management** for per-persona authentication and rotation.
- **Spec-driven Critic rails** honoring `allowed_topics` / `prohibited_topics`,
  wired input rails (prompt injection, input PII scan), full toxicity rail,
  and a circuit-breaker-aware escalation state machine.
- **Trainer that acts**: `RoutingController` applies model-reorder suggestions
  to the Sentinel; `PromptController` rotates prompts via the registry;
  `MaintenanceExecutor` drives `DegradationState` transitions.
- **Flask reference service** (`[service]` extra) with `/v1/query`,
  `/v1/feedback`, `/healthz`, `/readyz`, `/metrics`, `/v1/spec`, and a
  uniform error handler.
- **Test suite** at `tests/{unit,property,contract,integration}` with
  pytest, pytest-asyncio, hypothesis; coverage gate ≥ 85% on core packages.

### Changed

- Public entrypoint is now `from stc_framework import STCSystem`.
- Spec loader replaced with pydantic v2 models (`stc_framework.spec.models`);
  typos and schema violations now raise `SpecValidationError` at load time.
- `datetime.utcnow()` replaced by timezone-aware `datetime.now(timezone.utc)`.

### Removed

- Flat-layout Python modules at the repository root (`financial_qa_agent.py`,
  `gateway.py`, `governance_engine.py`, `optimization_manager.py`,
  `loader.py`, `run_*.py`); their functionality now lives under
  `src/stc_framework/`.
- Unused artifacts `files.zip` and `mnt/`.

### Security

- PII redaction is now enforced before model selection rather than after.
- Boundary crossings (`data_tier != "restricted"` → non-local model) are
  always audited.
- Default logging configuration drops `query` / `response` / `content` fields
  at INFO and above unless `STC_LOG_CONTENT=true` is set explicitly.
- **Security hardening pass** (see `docs/security/SECURITY_AUDIT.md`):
  - ReDoS-safe PII regex patterns with bounded quantifiers.
  - 16 prompt-injection rule families (multilingual, zero-width smuggling,
    base64, chat-markup, role-prefix spoofing, delimiter breakout).
  - Indirect prompt-injection defence — every retrieved chunk is
    sanitized before entering the context window.
  - Hard input-size / request-body / header-value caps at the boundary.
  - CR/LF/NUL stripping for header values to prevent log injection.
  - Data-sovereignty enforcement at spec-load, at
    `set_routing_preference`, and again at dispatch time.
  - Tokenizer removes the hardcoded fallback key; missing key in strict
    mode raises, otherwise a per-process random key is generated.
  - Encrypted token store file is written with mode `0o600` atomically.
  - Flask service sets `X-Content-Type-Options`, `X-Frame-Options`,
    `Referrer-Policy`, `Cache-Control: no-store`, HSTS; preserves
    Werkzeug HTTPException status codes.
  - Feedback endpoint constrained to an allow-list vocabulary.
  - Blocked-response text exposes rail names only, never reflects
    attacker-controlled content back to the caller.
- **Pre-deployment hardening for regulated environments** (see
  `docs/security/STAFF_REVIEW.md` — Round 2):
  - `WORMAuditBackend` (append-only, rotation-seal records, refuses
    `prune_before` / `erase_tenant` with `ComplianceViolation`).
  - Audit chain upgraded from SHA-256 to **HMAC-SHA256** keyed by
    `STC_AUDIT_HMAC_KEY`; `key_id` stamped per record; `verify_chain`
    accepts `accept_unknown_genesis=True` for post-prune verification.
  - `stc_framework.spec.signing` — ed25519 spec signature check at
    startup via `STC_SPEC_PUBLIC_KEY` (required in prod).
  - Strict prod-mode invariants enforced at `astart()`: HMAC key,
    tokenization strict, no content logs, no mock LLM, WORM backend,
    signed spec.
  - `AuditSpec.retention_policies` — per-event-class retention; SOX /
    FINRA-sensitive events default to 6 years; chain-seal records are
    retained forever.
  - `governance.erase_tenant` now clears idempotency cache, budget
    samples, and rate-limit bucket alongside audit / history / vector
    / token stores.
  - `JSONLAuditBackend.prune_before` writes a `retention_prune_seal`
    so the surviving chain remains verifiable.
  - `TenantBudgetTracker` uses calendar-day buckets with a monotonic
    sanity check — O(1) per operation, immune to wall-clock jumps.
  - `stc_framework.testing` — relocated `reset_*_for_tests` helpers
    that refuse to run when `STC_ENV=prod`.
  - `MockLLMClient` extracts numbers/citations from the CONTEXT block
    only and labels every response `[mock-llm]`.
  - `STCSpec.rail_by_name` memoized; `STCSystem.astart` warms Presidio.
- **Enterprise readiness & observability pass** (see
  `docs/operations/ENTERPRISE_READINESS.md`):
  - Per-stage latency histogram (`stc_stage_latency_ms`).
  - `stc_queries_total` now covers every outcome including
    `block_input` and `escalate`.
  - `stc_governance_events_total`, `stc_tenant_budget_usd`,
    `stc_tenant_budget_rejections_total`, `stc_adapter_healthcheck`,
    `stc_inflight_requests`, `stc_system_info` metrics added.
  - `tenant_label()` hashes high-cardinality tenant IDs so Prometheus
    storage is bounded.
  - Single `stc.aquery` parent span; every downstream span is a child,
    every structured log line carries `trace_id` / `span_id`.
  - `/readyz` probes every adapter and returns 503 on failure.
  - Per-tenant budget enforcement driven by
    `trainer.cost_thresholds` with audit + metric + typed error.
  - Idempotency-key support on `aquery` for safe retries.
  - `astart(strict_health=True)` fail-fast startup;
    `astop(drain_timeout=...)` graceful shutdown.
- **Data privacy & governance pass** (see
  `docs/security/GOVERNANCE_AUDIT.md`):
  - Tamper-evident hash-chained audit log with `verify_chain`.
  - 22-event `AuditEvent` catalogue; every query, rail failure,
    feedback, routing change, prompt rotation, retention sweep, DSAR
    export, and erasure call is now audited.
  - `governance.export_tenant_records` (DSAR, GDPR Art. 15 / CCPA §1798.100).
  - `governance.erase_tenant` (right to erasure, GDPR Art. 17).
  - `governance.apply_retention` (GDPR Art. 5(1)(e) storage limitation)
    driven by `audit.retention_days` in the spec.
  - Tenant filter on vector-store search; `list_for_tenant` /
    `erase_tenant` on the adapter Protocol.
  - Retrieved chunks are now PII-redacted before the LLM ever sees them.
  - Exception messages no longer reflect user content into logs / audit.
  - `Notifier` strips PII-risk fields before posting to Slack / logs.
  - `record_from_trace` filters raw query/response/context/chunks out
    of the Trainer's history store (data minimization).
  - New `CitationRequiredValidator` blocks numerical claims that lack
    a `[Source: ...]` citation.
  - Token store entries carry `tenant_id` + `created_at`; both
    implementations support `erase_tenant` and `prune_before`.

## [0.1.0] - Initial concept release

- Proof-of-concept with flat-file reference implementation of the
  Stalwart / Trainer / Critic architecture.
