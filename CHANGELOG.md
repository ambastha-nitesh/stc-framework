# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
