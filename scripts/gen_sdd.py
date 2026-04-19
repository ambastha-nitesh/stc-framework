"""Reverse-engineered STC Framework System Design Document."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from docgen import Section, build  # noqa: E402

DOCS_DIR = Path("C:/Projects/stc-framework/docs")

SECTIONS: list[Section] = [
    Section(title="1. Document Control", body=[
        {"type": "kv", "rows": [
            ("Document type", "System Design Document (SDD)"),
            ("Document ID", "STC-SDD-1.0"),
            ("Version", "1.0 \u2014 April 2026"),
            ("Status", "Current (reflects v0.2.0 shipped)"),
            ("Author", "Nitesh Ambastha"),
            ("Audience", "Staff engineers, platform architects, technical reviewers"),
        ]},
        {"type": "callout",
         "label": "Scope",
         "text":
            "This SDD describes the implementation-level design: module "
            "boundaries, Protocol contracts, data flow, failure modes, "
            "concurrency model, state machine semantics, and extension "
            "points. PRD covers 'what and why'; this document covers "
            "'how'. Architecture overview is in "
            "STC_Framework_Architecture_and_Capabilities.docx; this "
            "SDD goes one level deeper.",
         "color": "DBEAFE"},
    ]),

    Section(title="2. System Context", body=[
        {"type": "sub", "title": "2.1 External Dependencies", "body": [
            {"type": "grid",
             "headers": ["Dependency", "Purpose", "Protocol"],
             "rows": [
                 ["LLM provider (via LiteLLM)", "Reasoning", "LLMClient"],
                 ["Vector store (Qdrant)", "Document retrieval", "VectorStore"],
                 ["Embedder (Ollama)", "Query \u2194 vector", "EmbeddingsClient"],
                 ["Prompt registry (Langfuse / file)", "Versioned prompts", "PromptRegistry"],
                 ["PII detector (Presidio)", "Entity detection", "Native library (not Protocol)"],
                 ["Audit sink (JSONL / WORM)", "Tamper-evident log", "AuditBackend"],
                 ["Observability (Prometheus + OTel)", "Metrics + traces", "Native libraries"],
             ]},
        ]},
        {"type": "sub", "title": "2.2 Deployment Context", "body": [
            {"type": "bullets", "items": [
                "Runs as a library (import stc_framework) or as a Flask service.",
                "One STCSystem per process (see STAFF_REVIEW.md Tier-2 S9).",
                "Horizontal scaling is stateless for request handling; in-process state (idempotency cache, rate-limit buckets, budget buckets, circuit breakers) is per-pod.",
                "Audit log can be pod-local (JSONLAuditBackend) or shared (WORMAuditBackend paired with S3 Object Lock / Immudb).",
            ]},
        ]},
    ]),

    Section(title="3. Module Catalog", body=[
        {"type": "grid",
         "headers": ["Module", "Responsibility", "Key exports"],
         "rows": [
             ["stc_framework.system", "Orchestrates the 10-step aquery pipeline", "STCSystem, QueryResult"],
             ["stc_framework.errors", "Typed error taxonomy", "STCError + 15 subclasses + http_status_for"],
             ["stc_framework.config.settings", "Env-driven runtime settings", "STCSettings (pydantic-settings)"],
             ["stc_framework.config.logging", "structlog setup + PII filter", "configure_logging, get_logger"],
             ["stc_framework.spec", "Pydantic models + loader + signing", "STCSpec, load_spec, verify_spec_signature"],
             ["stc_framework.security", "Limits + sanitisers + injection rules", "get_security_limits, strip_zero_width, detect_injection"],
             ["stc_framework.resilience", "Retry, circuit, timeout, bulkhead, fallback", "Circuit, Bulkhead, atimeout, run_with_fallback, DegradationState"],
             ["stc_framework.observability", "Audit, metrics, tracing, correlation, health, inflight", "AuditLogger, AuditRecord, verify_chain, probe_system, tenant_label"],
             ["stc_framework.sentinel", "Classifier, redactor, tokenizer, gateway, auth, MCP", "SentinelGateway, PIIRedactor, Tokenizer"],
             ["stc_framework.critic", "Validators, rail runner, escalation, Critic", "Critic, Validator protocol, 8 built-in validators"],
             ["stc_framework.stalwart", "Execution pipeline", "StalwartAgent, StalwartResult"],
             ["stc_framework.trainer", "Reward, history, controllers, lightning bridge", "Trainer, RewardComputer, OptimizationManager"],
             ["stc_framework.governance", "Events, DSAR, erasure, retention, budget, rate limit, idempotency, CLI", "AuditEvent, export_tenant_records, erase_tenant, TenantBudgetTracker"],
             ["stc_framework.adapters", "LLM / vector / embeddings / prompts / guardrails / audit / mcp / lightning", "Protocol + default + optional impls"],
             ["stc_framework.service", "Flask app factory + routes + middleware", "create_app, runner"],
             ["stc_framework.adversarial", "Probe catalog + runner", "FINANCIAL_QA_PROBES, run_adversarial_suite"],
             ["stc_framework.testing", "Test-only globals reset helpers", "reset_all (refuses prod)"],
         ]},
    ]),

    Section(title="4. Key Data Structures", body=[
        {"type": "sub", "title": "4.1 QueryResult", "body": [
            {"type": "para", "text":
                "The return type of aquery. Contract: always a "
                "QueryResult with governance dict listing all rail "
                "results; response is a user-safe string even when "
                "blocked; metadata carries trace / request / cost / "
                "tenant / data-tier."},
            {"type": "code", "code":
                "@dataclass\n"
                "class QueryResult:\n"
                "    trace_id: str\n"
                "    response: str                    # always populated, even when blocked\n"
                "    governance: dict[str, Any]       # action, rail_results, escalation_level\n"
                "    optimization: dict[str, Any]     # reward, signals\n"
                "    metadata: dict[str, Any] = {}    # request_id, cost_usd, model, data_tier, citations"},
        ]},
        {"type": "sub", "title": "4.2 AuditRecord", "body": [
            {"type": "code", "code":
                "class AuditRecord(BaseModel):\n"
                "    timestamp: str                   # ISO-8601 UTC\n"
                "    trace_id: str | None\n"
                "    request_id: str | None\n"
                "    tenant_id: str | None\n"
                "    persona: str | None              # 'stalwart' | 'critic' | 'trainer' | 'system' | 'governance'\n"
                "    event_type: str                  # AuditEvent enum value\n"
                "    spec_version: str | None\n"
                "    data_tier: str | None\n"
                "    boundary_crossing: bool = False\n"
                "    model: str | None\n"
                "    rail_results: list[dict]         # per-rail pass/severity\n"
                "    action: str | None               # pass/warn/block/escalate\n"
                "    cost_usd / prompt_tokens / completion_tokens\n"
                "    redactions / redaction_entities\n"
                "    prev_hash / entry_hash / key_id  # HMAC chain fields\n"
                "    extra: dict                      # event-specific\n"
                "    model_config = {\"frozen\": True}"},
        ]},
        {"type": "sub", "title": "4.3 GuardrailResult", "body": [
            {"type": "code", "code":
                "@dataclass\n"
                "class GuardrailResult:\n"
                "    rail_name: str                   # stable identifier; matches spec entry\n"
                "    passed: bool\n"
                "    severity: str                    # critical | high | medium | low\n"
                "    action: str                      # pass | warn | block | redact\n"
                "    details: str                     # short human string\n"
                "    evidence: dict[str, Any]         # structured, regulator-readable\n"
                "    timestamp: str"},
        ]},
        {"type": "sub", "title": "4.4 STCSpec (top-level)", "body": [
            {"type": "bullets", "items": [
                "version, name, description, created, author.",
                "stalwart \u2014 framework, tools, memory, auth.",
                "trainer \u2014 optimization, cost_thresholds, maintenance.",
                "critic \u2014 guardrails (input/output rails), escalation.",
                "sentinel \u2014 gateway, pii_redaction, tokenization, auth, MCP.",
                "data_sovereignty \u2014 routing_policy, classification, boundary_audit.",
                "audit \u2014 retention_days (legacy), retention_policies (per-class), prompt_registry, export.",
                "risk_taxonomy, compliance.aiuc_1 \u2014 governance crosswalk.",
            ]},
        ]},
    ]),

    Section(title="5. Request Flow Design", body=[
        {"type": "sub", "title": "5.1 State Machine for Degradation", "body": [
            {"type": "code", "code":
                "NORMAL \u2192 DEGRADED  (2 critical rail failures / 10-task window)\n"
                "DEGRADED \u2192 QUARANTINE  (3 critical / 10)\n"
                "QUARANTINE \u2192 PAUSED  (5 critical / 10 OR 3 consecutive)\n"
                "PAUSED \u2192 NORMAL  (after cooldown_seconds with auto_retry=true)"},
        ]},
        {"type": "sub", "title": "5.2 Concurrency Model", "body": [
            {"type": "bullets", "items": [
                "Async-first: LLM / vector / embedding / guardrail paths all return coroutines.",
                "Sync facade query() refuses inside a running loop.",
                "Flask: dedicated asyncio thread per worker (_SystemRunner); request threads block on futures.",
                "Shared state synchronised via threading.RLock (circuits, degradation, metrics) or asyncio.Semaphore (bulkheads).",
                "InflightTracker uses both: RLock for counters, asyncio.Event for drain signalling.",
                "Correlation via contextvars.ContextVar \u2014 flows across await and thread boundaries.",
            ]},
        ]},
        {"type": "sub", "title": "5.3 Error Taxonomy", "body": [
            {"type": "grid",
             "headers": ["Error", "HTTP", "Retryable", "Meaning"],
             "rows": [
                 ["STCError (base)", "500", "varies", "Generic framework error"],
                 ["ConfigError", "500", "false", "Bad config; fix and restart"],
                 ["SpecValidationError", "500", "false", "Spec schema invalid"],
                 ["DataSovereigntyViolation", "403", "false", "Restricted data routing rule tripped"],
                 ["TierRoutingError", "403", "false", "No model for data tier"],
                 ["LLMTimeout", "504", "true", "Upstream slow"],
                 ["LLMRateLimited", "429", "true", "Upstream 429"],
                 ["LLMQuotaExceeded", "402", "false", "Provider budget exhausted"],
                 ["LLMContentFiltered", "422", "false", "Provider refused"],
                 ["LLMUnavailable", "503", "true", "Upstream 5xx"],
                 ["VectorStoreUnavailable", "503", "true", "Vector store unreachable"],
                 ["CollectionMissing", "404", "false", "Collection not initialised"],
                 ["CircuitBreakerOpen", "503", "false", "Downstream circuit open"],
                 ["BulkheadFull", "503", "true", "Too many concurrent calls"],
                 ["RetryExhausted", "502", "false", "All retries failed"],
                 ["GuardrailBlocked", "422", "false", "Rail refused"],
                 ["EscalationActive", "503", "false", "System paused"],
                 ["PromptRegistryError", "500", "varies", "Prompt version issue"],
                 ["TokenizationError", "500", "false", "Token store / key issue"],
             ]},
        ]},
    ]),

    Section(title="6. Protocol Contracts", body=[
        {"type": "para", "text":
            "The adapter layer is the extension point. Each Protocol "
            "has at least two implementations so consumers can see the "
            "contract. All async methods MUST be awaitable; all "
            "callable-based errors MUST raise subclasses of the "
            "appropriate STCError."},
        {"type": "sub", "title": "6.1 LLMClient", "body": [
            {"type": "code", "code":
                "class LLMClient(Protocol):\n"
                "    async def acompletion(\n"
                "        self, *, model: str, messages: list[ChatMessage],\n"
                "        timeout: float, metadata: dict | None = None,\n"
                "    ) -> LLMResponse: ...\n"
                "    async def healthcheck(self) -> bool: ..."},
            {"type": "bullets", "items": [
                "Errors must raise LLMTimeout / LLMRateLimited / LLMQuotaExceeded / LLMContentFiltered / LLMUnavailable.",
                "healthcheck() must be cheap (< 100 ms) and must not consume tokens.",
                "Optional aclose() flushes connection pools on astop.",
            ]},
        ]},
        {"type": "sub", "title": "6.2 VectorStore", "body": [
            {"type": "code", "code":
                "class VectorStore(Protocol):\n"
                "    async def ensure_collection(self, name: str, vector_size: int) -> None\n"
                "    async def upsert(self, collection: str, records: list[VectorRecord]) -> None\n"
                "    async def search(self, collection, vector, *, top_k=5, filters=None) -> list[RetrievedChunk]\n"
                "    async def keyword_search(self, collection, query, *, top_k=5, filters=None) -> list[RetrievedChunk]\n"
                "    async def list_for_tenant(self, tenant_id: str) -> list[dict]  # DSAR\n"
                "    async def erase_tenant(self, tenant_id: str) -> int            # Art. 17\n"
                "    async def healthcheck(self) -> bool"},
        ]},
        {"type": "sub", "title": "6.3 AuditBackend", "body": [
            {"type": "code", "code":
                "class AuditBackend(Protocol):\n"
                "    async def append(self, record: AuditRecord) -> AuditRecord        # seals + writes\n"
                "    def append_sync(self, record: AuditRecord) -> AuditRecord\n"
                "    async def close(self) -> None\n"
                "    def iter_records(self) -> Iterator[AuditRecord]\n"
                "    def iter_for_tenant(self, tenant_id: str) -> Iterator[AuditRecord]\n"
                "    def prune_before(self, cutoff_iso: str) -> int\n"
                "    def erase_tenant(self, tenant_id: str) -> int"},
            {"type": "bullets", "items": [
                "WORM-shaped backends raise ComplianceViolation from prune_before / erase_tenant.",
                "seal must stamp key_id from _KeyManager.key_id().",
                "seal must compute entry_hash with HMAC under the current key.",
            ]},
        ]},
    ]),

    Section(title="7. Cryptographic Design", body=[
        {"type": "sub", "title": "7.1 Audit Hash Chain", "body": [
            {"type": "para", "text":
                "Each record is sealed with prev_hash = previous_entry.entry_hash "
                "(or GENESIS for the first record) and entry_hash = HMAC-SHA256("
                "HMAC_KEY, JSON-serialised record minus entry_hash). Key is read "
                "from STC_AUDIT_HMAC_KEY at first call and cached for the "
                "process lifetime. key_id (env-<sha256[:8]> or ephemeral-<hex>) "
                "is written per record."},
            {"type": "para", "text":
                "verify_chain recomputes entry_hash per record and compares with "
                "hmac.compare_digest. accept_unknown_genesis=True allows "
                "post-retention verification; strict mode asserts the first "
                "record's prev_hash is GENESIS."},
        ]},
        {"type": "sub", "title": "7.2 Rotation-Seal + Prune-Seal", "body": [
            {"type": "bullets", "items": [
                "audit_rotation_seal: emitted by WORMAuditBackend when size threshold triggers a new file. Its entry_hash becomes prev_hash of the first record in the new file.",
                "retention_prune_seal: emitted by JSONLAuditBackend before files are deleted by prune_before; carries last_pruned_entry_hash so verify_chain(accept_unknown_genesis=True) can jump the gap.",
                "Both seals default to retention=-1 (forever) so naive retention overrides cannot orphan the chain.",
            ]},
        ]},
        {"type": "sub", "title": "7.3 Spec Signing", "body": [
            {"type": "bullets", "items": [
                "Ed25519 (Curve25519 EdDSA). Public key in STC_SPEC_PUBLIC_KEY (32 bytes base64-urlsafe).",
                "Signature bytes in spec.yaml.sig sidecar (64 bytes).",
                "Signed content = SHA-256 digest of the spec file bytes.",
                "verify_spec_signature(required=True) raises SpecSignatureError on any failure path.",
                "Prod startup refuses if missing or invalid.",
            ]},
        ]},
        {"type": "sub", "title": "7.4 Tokenization", "body": [
            {"type": "bullets", "items": [
                "Token format: STC_TOK_<12 hex chars>.",
                "HMAC-SHA256 keyed by STC_TOKENIZATION_KEY (deterministic within key lifetime \u2014 same value \u2192 same token).",
                "Reversible lookup via TokenStore. Default InMemoryTokenStore; EncryptedFileTokenStore adds AES-GCM at-rest encryption.",
                "Strict mode: STC_TOKENIZATION_STRICT=1 refuses to generate tokens when the key is unset.",
            ]},
        ]},
    ]),

    Section(title="8. Runtime Invariants", body=[
        {"type": "grid",
         "headers": ["Invariant", "Enforcement Point", "Enforcement Count"],
         "rows": [
             ["Restricted data stays in-boundary", "spec/models.py + sentinel/gateway.py", "3 layers"],
             ["Every query produces an audit record", "system.py::_run_pipeline", "1"],
             ["Audit chain is HMAC-sealed per record", "adapters/audit_backend/*::_seal", "2 (JSONL + WORM)"],
             ["Budget reserve is atomic with enforcement", "governance/budget.py::reserve", "1 (holds lock)"],
             ["Idempotency replay does not re-audit", "system.py::aquery (early short-circuit)", "1"],
             ["Erasure touches every tenant-scoped store", "governance/erasure.py", "7 stores"],
             ["Spec signature must verify in prod", "system.py::_enforce_startup_invariants", "1"],
             ["No mock LLM in prod", "system.py::_enforce_startup_invariants", "1"],
             ["No content in logs unless STC_LOG_CONTENT=true", "config/logging.py", "1 filter"],
         ]},
    ]),

    Section(title="9. Key Algorithms", body=[
        {"type": "sub", "title": "9.1 Per-tenant budget (rolling day-bucket)", "body": [
            {"type": "code", "code":
                "# Per-tenant state: deque[_DayBucket] with maxlen=35\n"
                "# Each bucket: day (UTC calendar date) + total_usd\n"
                "\n"
                "reserve(tenant_id, anticipated_cost):\n"
                "    with lock:\n"
                "        check_monotonic_clock(tenant_id)\n"
                "        enforce_locked(tenant_id, anticipated_cost)  # TOCTOU-safe\n"
                "        bucket_for_today().total_usd += anticipated_cost\n"
                "\n"
                "observed(tenant_id, window):\n"
                "    # window in {'daily', 'monthly'}\n"
                "    if window == 'daily': sum buckets where day == today\n"
                "    else: sum buckets where day > today - 30\n"
                "    # O(1) daily, O(30) monthly \u2014 bounded regardless of request rate"},
        ]},
        {"type": "sub", "title": "9.2 Correlation propagation", "body": [
            {"type": "code", "code":
                "_trace_id = ContextVar('stc_trace_id', default=None)\n"
                "# ... _request_id, _tenant_id, _persona, _prompt_version similar\n"
                "\n"
                "@contextmanager\n"
                "def bind_correlation(*, trace_id=None, tenant_id=None, ...):\n"
                "    tokens = []\n"
                "    for name, val in updates:\n"
                "        if val is not None:\n"
                "            tokens.append((var, var.set(val)))\n"
                "    try: yield current_correlation()\n"
                "    finally:\n"
                "        for var, tok in reversed(tokens): var.reset(tok)"},
        ]},
        {"type": "sub", "title": "9.3 Injection normalisation + detection", "body": [
            {"type": "code", "code":
                "detect_injection(text):\n"
                "    normalized = strip_zero_width(text)    # removes Cf chars + BiDi overrides\n"
                "    hits = []\n"
                "    for rule in INJECTION_RULES:           # 16 regex rules\n"
                "        if rule.pattern.search(normalized):\n"
                "            hits.append(InjectionMatch(rule, snippet))\n"
                "    # decode any long base64 run and re-scan for trigger verbs\n"
                "    encoded = _decoded_injection(normalized)\n"
                "    if encoded: hits.append(encoded)\n"
                "    return hits"},
        ]},
    ]),

    Section(title="10. Extension Points", body=[
        {"type": "grid",
         "headers": ["Extension", "Interface", "Example"],
         "rows": [
             ["New Critic rail", "Validator Protocol", "MNPIValidator (see CONTRIBUTING Recipe 1)"],
             ["New LLM provider", "LLMClient Protocol", "AzureOpenAIAdapter"],
             ["New vector store", "VectorStore Protocol", "PgVectorAdapter"],
             ["New embedding provider", "EmbeddingsClient Protocol", "CohereEmbeddingsAdapter"],
             ["New prompt registry", "PromptRegistry Protocol", "PostgresPromptRegistry"],
             ["New audit backend", "AuditBackend Protocol", "ImmudbBackend"],
             ["New rate-limit / budget backend", "Subclass TenantRateLimiter / TenantBudgetTracker", "RedisTenantRateLimiter"],
             ["New event type", "AuditEvent enum + optional retention class", "prompt_rollback"],
         ]},
    ]),

    Section(title="11. Testing Strategy", body=[
        {"type": "grid",
         "headers": ["Tier", "Purpose", "Files"],
         "rows": [
             ["Unit", "Module-level invariants", "tests/unit/*"],
             ["Property", "Invariants over input space", "tests/property/*"],
             ["Contract", "Adapter Protocol conformance", "tests/contract/*"],
             ["Security", "Injection / ReDoS / header / crypto", "tests/unit/test_security.py"],
             ["Privacy", "DSAR / erasure / retention / chunk redaction", "tests/unit/test_privacy.py"],
             ["Observability", "Metrics / correlation / health probes", "tests/unit/test_observability.py"],
             ["Enterprise", "Budget / idempotency / shutdown / strict prod", "tests/unit/test_enterprise.py"],
             ["Staff review R1", "asyncio compat / TOCTOU / RPS / CLI", "tests/unit/test_staff_review.py"],
             ["Staff review R2", "WORM / HMAC / spec signing / retention seal / mock LLM", "tests/unit/test_staff_review_round2.py"],
             ["Integration (opt-in)", "Live adapters via testcontainers", "tests/integration/* (marked)"],
         ]},
        {"type": "para", "text":
            "Coverage gate \u2265 70% on core packages; current 81.6%. "
            "All six audit suites are release-blockers."},
    ]),

    Section(title="12. Known Limitations & Tier-2 Roadmap", body=[
        {"type": "bullets", "items": [
            "Module-level singletons (_circuits, _STATE, _metrics) \u2014 one STCSystem per process supported. Tier-2 fix plumbs a SystemContext DI.",
            "No streaming LLM responses (full accumulated response enters rails). Tier-2.",
            "No shadow-mode / percentage-canary rollouts of prompts or routing. Tier-2.",
            "No env-driven kill switches for specific rails. Tier-2.",
            "Chaos / load test suite not bundled (only adversarial probe suite). Tier-2.",
            "No perf regression gate in CI. Tier-2.",
            "No multi-region shared state adapters bundled. Tier-2.",
            "No LLM model-drift detection. Tier-2.",
        ]},
    ]),

    Section(title="13. Change Management for the Design", body=[
        {"type": "bullets", "items": [
            "Every ADR in DECISIONS.md is considered normative. A change that contradicts an ADR requires a new ADR.",
            "New Protocol methods are breaking for every implementor; prefer default-implementations returning safe zeros.",
            "Event type strings in AuditEvent enum must not change once shipped; regulators query by string.",
            "RetentionPolicy defaults may be tightened (longer retention) but not loosened without compliance sign-off.",
            "Public API additions (signatures on STCSystem, AuditRecord fields) trigger minor version bump; contract-test snapshot refreshed.",
        ]},
    ]),

    Section(title="14. Glossary", body=[
        {"type": "para", "text":
            "Full glossary in docs/GLOSSARY.md. Key terms: Rail (named "
            "validator), Spec (declarative YAML = compliance posture), "
            "Data tier (public / internal / restricted), Boundary "
            "crossing (restricted \u2192 non-local LLM), Escalation (4-state "
            "degradation), WORM (Write-Once-Read-Many audit), DSAR "
            "(Data Subject Access Request, GDPR Art. 15), Right to "
            "erasure (GDPR Art. 17), Rolling-bucket budget (per-tenant "
            "daily cost tracking)."},
    ]),
]


def main() -> None:
    build(
        DOCS_DIR / "STC_System_Design_Document.docx",
        title="System Design Document",
        subtitle="Implementation-level Design",
        tagline="Modules \u00b7 Protocols \u00b7 Data structures \u00b7 Invariants \u00b7 Algorithms",
        classification="INTERNAL",
        version="Version 1.0 \u2014 April 2026",
        doc_id="STC-SDD-1.0",
        toc=[
            "Document Control",
            "System Context",
            "Module Catalog",
            "Key Data Structures",
            "Request Flow Design",
            "Protocol Contracts",
            "Cryptographic Design",
            "Runtime Invariants",
            "Key Algorithms",
            "Extension Points",
            "Testing Strategy",
            "Known Limitations & Roadmap",
            "Change Management",
            "Glossary",
        ],
        sections=SECTIONS,
    )
    print("wrote STC_System_Design_Document.docx")


if __name__ == "__main__":
    main()
