"""Reverse-engineered STC Framework Jira Specification.

Every epic and story traces to code that already exists. Intended as
the backlog you would have planned on day one if you'd known how the
product would end up.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from docgen import Section, build  # noqa: E402

DOCS_DIR = Path("C:/Projects/stc-framework/docs")


# Helpers for concise story tables ------------------------------------------


def story(key: str, title: str, ac: list[str], priority: str = "High", points: int = 5) -> list[str]:
    return [key, title, priority, str(points), "\n".join(f"\u2022 {a}" for a in ac)]


# Each epic becomes a sub-section with a narrative + story table.

SECTIONS: list[Section] = [
    Section(title="1. Document Control", body=[
        {"type": "kv", "rows": [
            ("Document type", "Jira Specification"),
            ("Document ID", "STC-JIRA-1.0"),
            ("Version", "1.0 \u2014 April 2026 (reverse-engineered)"),
            ("Epics", "14"),
            ("Stories", "~95"),
            ("Product version covered", "v0.2.0 (shipped)"),
            ("Status", "All stories completed; retained as the master backlog"),
        ]},
        {"type": "callout",
         "label": "How to read this document",
         "text":
            "Each epic lists its child stories with acceptance criteria "
            "(ACs) and priority. Priority encodes the actual order we "
            "discovered items \u2014 not an arbitrary guess. ACs are "
            "pulled from the passing regression tests, so \"story closes "
            "when ACs pass\" is literally true in the codebase.",
         "color": "DBEAFE"},
    ]),

    Section(title="2. Epic STC-E1 \u2014 Core Pipeline", body=[
        {"type": "kv", "rows": [
            ("Epic key", "STC-E1"),
            ("Goal", "A caller with a query + tenant gets a governed response via one async entrypoint."),
            ("Files", "src/stc_framework/system.py; stalwart/agent.py"),
            ("Exit criteria", "aquery runs the 10-step pipeline; test_privacy::TestAuditCoverage passes"),
        ]},
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-1", "STCSystem.aquery async entrypoint", [
                 "Signature: async aquery(query, *, tenant_id=None, idempotency_key=None) -> QueryResult",
                 "Sync facade raises if run inside a running loop",
                 "Tests: test_system.py",
             ], "Critical", 8),
             story("STC-2", "Input sanitisation + size limits", [
                 "Query > 8KB raises STCError",
                 "Non-string raises STCError",
                 "Zero-width / BiDi normalised before rails",
                 "Header values CR/LF/NUL stripped",
                 "Tests: test_security.py::TestInputLimits + TestSanitizerInvariants",
             ], "Critical"),
             story("STC-3", "Ten-step pipeline order preserved", [
                 "Order: limits \u2192 idempotency \u2192 shutdown \u2192 degradation \u2192 RPS \u2192 budget \u2192 correlation \u2192 input rails \u2192 stalwart \u2192 output rails \u2192 audit + settle",
                 "Each step can short-circuit to an audited rejection",
                 "Tests: test_enterprise.py + test_staff_review.py",
             ]),
             story("STC-4", "Sync query() facade", [
                 "Refuses inside a live event loop with clear error",
                 "Wraps aquery() via asyncio.run()",
             ], "Medium", 2),
         ]},
    ]),

    Section(title="3. Epic STC-E2 \u2014 Sentinel Infrastructure", body=[
        {"type": "kv", "rows": [
            ("Epic key", "STC-E2"),
            ("Goal", "Trust boundary: classify, redact, tokenize, route, audit."),
            ("Files", "src/stc_framework/sentinel/*"),
        ]},
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-5", "DataClassifier with custom patterns", [
                 "Spec-declared regex + keyword patterns win before Presidio",
                 "Presidio BLOCK-list entities promote tier to restricted",
                 "Tests: test_classifier.py + test_privacy",
             ]),
             story("STC-6", "PIIRedactor with BLOCK action", [
                 "BLOCK entities raise DataSovereigntyViolation",
                 "ReDoS-safe bounded-quantifier regex",
                 "Regex fallback works without Presidio installed",
                 "Tests: test_redaction.py + test_security::TestReDoSHardening",
             ]),
             story("STC-7", "Surrogate tokenization + AES-GCM store", [
                 "Tokens STC_TOK_<12 hex>",
                 "HMAC-SHA256 keyed by STC_TOKENIZATION_KEY",
                 "File mode 0o600 on POSIX, atomic O_NOFOLLOW",
                 "tenant_id + created_at per entry",
                 "erase_tenant + prune_before supported",
                 "Strict mode required in prod",
                 "Tests: test_tokenization.py + test_privacy::TestTokenStoreGovernance",
             ], "High"),
             story("STC-8", "SentinelGateway with 3-layer data-sovereignty enforcement", [
                 "Spec load rejects cloud model in restricted tier",
                 "set_routing_preference refuses unknown / foreign models",
                 "Dispatch re-checks tier before calling provider",
                 "Tests: test_security::TestDataSovereigntyEnforcement",
             ], "Critical", 8),
             story("STC-9", "VirtualKeyManager per-persona keys", [
                 "issue / rotate / authorize / verify_bearer",
                 "Scope-bounded permissions",
                 "Tests: test_virtual_keys.py",
             ], "Medium"),
             story("STC-10", "MCP access policy deny-by-default", [
                 "Trusted-agent allow-list",
                 "Tool risk-tier vs data-tier check",
                 "Tests: test_mcp_policy.py",
             ], "Medium"),
         ]},
    ]),

    Section(title="4. Epic STC-E3 \u2014 Stalwart Execution Plane", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-11", "Async RAG pipeline (classify \u2192 retrieve \u2192 reason)", [
                 "Each stage wrapped in retry + circuit + timeout + bulkhead",
                 "Per-stage latency in stc_stage_latency_ms histogram",
                 "Tests: test_observability + test_system",
             ]),
             story("STC-12", "Chunk PII redaction (indirect-PII defence)", [
                 "PIIRedactor runs on every retrieved chunk pre-LLM",
                 "BLOCK-listed chunks dropped with warning",
                 "Tests: test_privacy::TestPIILeakSurface",
             ], "High"),
             story("STC-13", "Tenant-filtered vector search", [
                 "tenant_id filter passed on every search",
                 "Fallback keyword search also filtered",
                 "Tests: test_privacy::TestTenantIsolation",
             ]),
             story("STC-14", "Exception-path PII protection", [
                 "StalwartResult.error stores exception class name only",
                 "Tests: test_privacy::test_pipeline_error_does_not_echo_exception_message",
             ], "Medium"),
             story("STC-15", "Citation extraction", [
                 "Regex extracts [Source: ...] and [Document: ...]",
                 "Citations returned in QueryResult.metadata",
             ], "Low"),
         ]},
    ]),

    Section(title="5. Epic STC-E4 \u2014 Critic Governance Plane", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-16", "Validator Protocol + 8 built-in rails", [
                 "rail_name is a class attribute",
                 "Async avalidate returning GuardrailResult",
                 "Rails: injection, numerical, hallucination, scope, PII, toxicity, citation, output-injection",
                 "Tests: test_*_validator.py + test_staff_review_round2",
             ], "Critical", 13),
             story("STC-17", "RailRunner with bulkhead + timeout", [
                 "Unknown rail names logged once and skipped",
                 "Rail exceptions converted to warn-severity failures",
                 "Tests: test_system.py (indirect)",
             ]),
             story("STC-18", "EscalationManager 4-state machine", [
                 "NORMAL \u2192 DEGRADED \u2192 QUARANTINE \u2192 PAUSED",
                 "Consecutive-failure circuit breaker with cooldown",
                 "Auto-retry after cooldown elapses",
                 "Tests: test_escalation.py",
             ], "High"),
             story("STC-19", "Numerical accuracy validator", [
                 "Numbers in response grounded in source chunks",
                 "Spec-driven tolerance_percent",
                 "Tests: test_numerical_validator.py + property test",
             ]),
             story("STC-20", "Hallucination detector (grounding)", [
                 "Default: content-word overlap threshold",
                 "Optional: embedding cosine similarity",
                 "Tests: test_hallucination_validator.py",
             ]),
             story("STC-21", "Citation required validator", [
                 "Numerical claim without [Source:] blocks",
                 "No numbers \u2192 passes",
                 "Tests: test_privacy::TestCitationRequired",
             ], "High"),
             story("STC-22", "Scope / investment advice validator", [
                 "Prohibited topics blocked",
                 "Allowed topics warn if unmatched",
                 "Tests: test_scope_validator.py",
             ]),
             story("STC-23", "Prompt-injection input + output rails", [
                 "16 rule families",
                 "Zero-width normalisation pre-rule",
                 "Base64-decoded payload detection",
                 "Tests: test_injection_validator.py + test_security",
             ], "Critical", 8),
         ]},
    ]),

    Section(title="6. Epic STC-E5 \u2014 Trainer Optimization Plane", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-24", "Trace-driven reward computation", [
                 "Retrieval quality + factual accuracy + user feedback",
                 "Weighted composite reward",
                 "Tests: test_reward.py",
             ], "Medium"),
             story("STC-25", "Pluggable HistoryStore (memory + SQLite)", [
                 "Protocol with erase_tenant + prune_before",
                 "record_from_trace filters PII fields from metadata",
                 "Tests: test_privacy::TestPIILeakSurface",
             ], "Medium"),
             story("STC-26", "OptimizationManager health signals", [
                 "Accuracy / cost / latency / hallucination triggers",
                 "Maintenance recommendation output",
                 "Tests: test_optimizer.py",
             ]),
             story("STC-27", "RoutingController applies spec-bounded reorder", [
                 "Refuses models not declared in spec's tier",
                 "Refuses cloud models in restricted tier",
                 "Emits routing_updated audit + stc_queries_total label",
                 "Tests: test_trainer_controllers.py + test_security",
             ], "High"),
             story("STC-28", "PromptController with versioned registry", [
                 "publish(name, version, content, activate)",
                 "Emits prompt_registered + prompt_activated",
                 "Tests: test_prompt_registry.py",
             ], "Medium"),
             story("STC-29", "Agent Lightning bridge", [
                 "Transition tuple format",
                 "InMemoryRecorder default",
                 "Optional real adapter behind [lightning] extra",
             ], "Low"),
             story("STC-30", "MaintenanceExecutor + Notifier", [
                 "Drives DegradationState from trigger reports",
                 "Slack webhook scrubs PII via _strip_pii",
                 "Tests: test_trainer_controllers.py + test_privacy",
             ]),
         ]},
    ]),

    Section(title="7. Epic STC-E6 \u2014 Observability & Audit", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-31", "AuditRecord pydantic model + AuditLogger", [
                 "26 event types in AuditEvent enum",
                 "Every emit bumps stc_governance_events_total",
                 "Tests: test_privacy::TestAuditCoverage",
             ], "Critical"),
             story("STC-32", "HMAC-SHA256 hash chain with key_id", [
                 "STC_AUDIT_HMAC_KEY required in prod; ephemeral in dev",
                 "key_id stamped per record for rotation",
                 "verify_chain supports accept_unknown_genesis",
                 "Tests: test_staff_review_round2::TestHMACChain",
             ], "Critical", 8),
             story("STC-33", "JSONLAuditBackend with rotation + prune seal", [
                 "Daily rotation at rotate_bytes size",
                 "prune_before writes retention_prune_seal",
                 "erase_tenant rewrites chain",
                 "Tests: test_staff_review_round2::TestRetentionChainSeal",
             ], "High"),
             story("STC-34", "WORMAuditBackend for SEC 17a-4", [
                 "erase_tenant + prune_before raise ComplianceViolation",
                 "audit_rotation_seal bridges file boundaries",
                 "fsync on every write",
                 "Tests: test_staff_review_round2::TestWORMBackend",
             ], "Critical"),
             story("STC-35", "17 Prometheus metrics", [
                 "Per-stage latency, budget, rejections, inflight, adapter health",
                 "tenant_label bounds cardinality",
                 "Tests: test_observability.py",
             ], "High"),
             story("STC-36", "OpenTelemetry root span + correlation ContextVars", [
                 "stc.aquery parent span per query",
                 "trace_id, request_id, tenant_id, persona in contextvars",
                 "Every log and span reads from the same snapshot",
                 "Tests: test_observability::TestCorrelationBinding",
             ]),
             story("STC-37", "structlog JSON logs with PII filter", [
                 "trace_id / span_id auto-bound",
                 "query / response / content fields dropped unless STC_LOG_CONTENT=true",
                 "Tests: config/logging.py",
             ]),
             story("STC-38", "Adapter healthcheck + /readyz", [
                 "Each adapter exposes healthcheck()",
                 "/readyz probes with short timeout",
                 "Tests: test_observability::TestHealthProbe",
             ]),
         ]},
    ]),

    Section(title="8. Epic STC-E7 \u2014 Governance & Subject Rights", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-39", "DSAR export across all tenant-scoped stores", [
                 "Returns audit + history + vectors + prompts in single JSON",
                 "Export itself audited (dsar_export)",
                 "Tests: test_privacy::TestDSAR",
             ], "High"),
             story("STC-40", "Right-to-erasure across 7 stores", [
                 "Audit, history, vectors, tokens, idempotency, budget, rate limiter",
                 "Erasure receipt tenant_id=None so second call doesn't delete it",
                 "Tests: test_privacy::TestErasure + test_staff_review_round2::TestIdempotencyClearedOnErase",
             ], "Critical", 8),
             story("STC-41", "Per-event-class retention policies", [
                 "Erasure + DSAR + boundary + escalation default 6 years",
                 "Chain seals forever (-1)",
                 "prune refused when any class is forever",
                 "Tests: test_staff_review_round2::TestPerEventRetention",
             ], "High"),
             story("STC-42", "stc-governance CLI", [
                 "Subcommands: verify-chain / dsar / erase --yes / retention",
                 "Erase requires explicit --yes",
                 "Tests: test_staff_review::TestGovernanceCLI",
             ], "Medium"),
             story("STC-43", "Ed25519 spec signature verification", [
                 "spec.yaml.sig sidecar",
                 "Prod-required; dev-optional; tampered always raises",
                 "sign_spec helper for CI",
                 "Tests: test_staff_review_round2::TestSpecSignature",
             ], "Critical"),
         ]},
    ]),

    Section(title="9. Epic STC-E8 \u2014 Production Safety", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-44", "TenantBudgetTracker (calendar-day buckets)", [
                 "UTC day buckets, 35-day ring, O(1) observed()",
                 "reserve/settle atomic against TOCTOU",
                 "Monotonic clock sanity check",
                 "Refund on crash + input-rail-block paths",
                 "Tests: test_staff_review_round2::TestBudgetDayBuckets",
             ], "Critical", 8),
             story("STC-45", "TenantRateLimiter (token bucket, bounded)", [
                 "Per-tenant; LRU eviction above max_tenants",
                 "Retryable rejection (clients back off)",
                 "Tests: test_staff_review::TestRateLimiter",
             ], "High"),
             story("STC-46", "IdempotencyCache (LRU + TTL, tenant-scoped)", [
                 "Key = (tenant_id, idempotency_key)",
                 "Cache cleared on erasure",
                 "Tests: test_enterprise::TestIdempotency + test_staff_review_round2::TestIdempotencyClearedOnErase",
             ], "High"),
             story("STC-47", "Graceful shutdown with in-flight drain", [
                 "SIGTERM registers clean drain (30s default)",
                 "_stopping flag rejects new requests",
                 "Adapters aclose() in order; audit closes last",
                 "Tests: test_enterprise::TestGracefulShutdown",
             ], "High"),
             story("STC-48", "Strict prod startup invariants", [
                 "6 invariants enforced at astart()",
                 "Missing HMAC / mock LLM / non-WORM / unsigned spec all raise",
                 "Tests: test_staff_review_round2::TestStrictProdMode",
             ], "Critical"),
             story("STC-49", "Presidio warmup + adapter aclose", [
                 "Warm Presidio at astart",
                 "astop calls aclose() on every adapter",
                 "Tests: test_staff_review::TestAdapterClose",
             ], "Medium"),
         ]},
    ]),

    Section(title="10. Epic STC-E9 \u2014 Resilience", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-50", "Tenacity-style retry with full-jitter backoff", [
                 "Retries only on retryable STCError subclasses",
                 "Per-downstream attempt counters in metrics",
                 "Tests: test_resilience::TestRetryTransient",
             ]),
             story("STC-51", "Per-downstream async circuit breaker", [
                 "fail_max + reset_timeout",
                 "Half-open probe after cooldown",
                 "State emitted as gauge",
                 "Tests: test_resilience",
             ], "High"),
             story("STC-52", "Async timeout helper (3.10/3.11 compat)", [
                 "asyncio.timeout on 3.11+, wait_for shim on 3.10",
                 "Tests: test_staff_review::TestTimeoutPy310Compat",
             ]),
             story("STC-53", "Bulkhead (asyncio Semaphore)", [
                 "Per-downstream concurrency cap",
                 "try_acquire non-blocking path",
                 "Tests: test_resilience",
             ]),
             story("STC-54", "Declarative fallback chain", [
                 "run_with_fallback iterates alternates",
                 "Respects retryable flag",
                 "Tests: test_resilience",
             ]),
             story("STC-55", "DegradationState singleton", [
                 "NORMAL \u2192 DEGRADED \u2192 QUARANTINE \u2192 PAUSED",
                 "pub-sub listeners",
                 "Tests: test_degradation.py",
             ]),
         ]},
    ]),

    Section(title="11. Epic STC-E10 \u2014 Declarative Specification", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-56", "Pydantic v2 STCSpec model", [
                 "Every section typed; extra='allow' where sensible",
                 "routing_policy validator rejects invalid tiers",
                 "Tests: test_spec_loader.py",
             ], "Critical"),
             story("STC-57", "load_spec with ${ENV} interpolation", [
                 "SpecValidationError on schema failure",
                 "Env resolution before validation",
                 "Tests: test_spec_loader.py",
             ]),
             story("STC-58", "RetentionPolicy pydantic model", [
                 "Per-event-class defaults",
                 "-1 sentinel for forever",
                 "days_for() falls back to default",
                 "Tests: test_staff_review_round2::TestPerEventRetention",
             ]),
             story("STC-59", "rail_by_name memoization", [
                 "Cached dict built once per spec",
                 "Tests: test_staff_review_round2::TestRailByNameMemoized",
             ], "Low"),
         ]},
    ]),

    Section(title="12. Epic STC-E11 \u2014 Adapter Layer", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-60", "LLMClient Protocol + MockLLMClient + LiteLLMAdapter", [
                 "acompletion returns typed LLMResponse",
                 "Errors mapped to LLMError taxonomy",
                 "MockLLMClient extracts only from CONTEXT and tags [mock-llm]",
                 "Tests: test_llm_contract.py + test_staff_review_round2::TestMockLLMUsesContext",
             ]),
             story("STC-61", "VectorStore Protocol + InMemoryVectorStore + QdrantAdapter", [
                 "search + keyword_search with filters",
                 "list_for_tenant + erase_tenant for governance",
                 "Tests: test_vector_contract.py",
             ]),
             story("STC-62", "EmbeddingsClient Protocol + HashEmbedder + OllamaEmbeddings", [
                 "Deterministic HashEmbedder default",
                 "Ollama REST adapter optional",
                 "Tests: test_observability.py",
             ]),
             story("STC-63", "PromptRegistry Protocol + FilePromptRegistry + Langfuse", [
                 "Versioned prompts; one active at a time",
                 "register + get + set_active + list_versions",
                 "Tests: test_prompt_registry.py",
             ]),
             story("STC-64", "AuditBackend Protocol + JSONL + WORM + Parquet export", [
                 "append + append_sync + iter_records",
                 "erase_tenant + prune_before per policy",
                 "Tests: many",
             ], "High"),
             story("STC-65", "External guardrail adapters (NeMo, Guardrails AI)", [
                 "Lazy imports gated on [nemo] / [guardrails-ai] extras",
                 "Exceptions mapped to GuardrailError",
             ], "Low"),
         ]},
    ]),

    Section(title="13. Epic STC-E12 \u2014 Flask Service", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-66", "Flask app factory with per-worker asyncio loop thread", [
                 "_SystemRunner bridges WSGI sync \u2194 async",
                 "MAX_CONTENT_LENGTH = 64 KiB",
                 "Security headers (X-Frame, X-Content-Type, Referrer, HSTS, Cache-Control)",
             ]),
             story("STC-67", "/v1/query endpoint", [
                 "Accepts JSON body",
                 "Oversized \u2192 413",
                 "Non-string query \u2192 400",
                 "Tests: test_security::TestFlaskService",
             ], "High"),
             story("STC-68", "/v1/feedback allow-list", [
                 "Restricted vocabulary",
                 "Oversized trace_id \u2192 400",
             ]),
             story("STC-69", "/healthz, /readyz, /metrics, /v1/spec", [
                 "/readyz probes adapters",
                 "/metrics Prometheus exposition",
             ]),
             story("STC-70", "SIGTERM handler runs runner.shutdown(30)", [
                 "K8s preStop compatible",
                 "terminationGracePeriodSeconds \u2265 35",
             ], "High"),
             story("STC-71", "HTTPException handler preserves 4xx codes", [
                 "413, 404, 405 etc. not masked as 500",
             ]),
             story("STC-72", "flask-limiter (optional)", [
                 "Keyed by X-Tenant-Id",
                 "Memory backend default",
             ], "Medium"),
         ]},
    ]),

    Section(title="14. Epic STC-E13 \u2014 Supply Chain & CI", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-73", "pip-audit CVE scan in CI", [
                 "Fails on fixable CVE in dependency tree",
             ], "High"),
             story("STC-74", "CycloneDX SBOM artifact per CI run", [
                 "Uploaded as artifact; retained per release",
             ]),
             story("STC-75", "Regex secret scan blocks obvious keys", [
                 "AWS AKIA, OpenAI sk-, Slack xoxb, private keys",
             ]),
             story("STC-76", "Python matrix: 3.10, 3.11, 3.12", []),
             story("STC-77", "ruff + black + mypy + coverage gate \u2265 70%", []),
         ]},
    ]),

    Section(title="15. Epic STC-E14 \u2014 Documentation", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-78", "ARCHITECTURE.md + Mermaid diagrams", []),
             story("STC-79", "DECISIONS.md ADR-style \u00d7 5", []),
             story("STC-80", "GOTCHAS.md + GLOSSARY.md + FAQ.md", []),
             story("STC-81", "GUIDED_TOUR.md (10-minute onboarding)", []),
             story("STC-82", "CONTRIBUTING.md with 5 step-by-step recipes", []),
             story("STC-83", "operations/RUNBOOK.md (alerts + incident response)", []),
             story("STC-84", "security/SECURITY_AUDIT.md + GOVERNANCE_AUDIT.md + STAFF_REVIEW.md", []),
             story("STC-85", "operations/ENTERPRISE_READINESS.md", []),
             story("STC-86", "This Jira spec + PRD + System Design Doc", []),
             story("STC-87", "STC_Framework_Showcase.html (marketing)", []),
         ]},
    ]),

    Section(title="16. Epic STC-E15 \u2014 Adversarial Testing", body=[
        {"type": "grid",
         "headers": ["Key", "Title", "Pri", "SP", "Acceptance Criteria"],
         "rows": [
             story("STC-88", "Probe catalog (MITRE ATLAS)", [
                 "8 baseline probes across prompt injection, data exfil, hallucination, jailbreak",
                 "Tests: test_adversarial.py",
             ]),
             story("STC-89", "adversarial.runner with AIUC-1 report", [
                 "Critical pass rate 100%; overall \u2265 90%",
                 "CLI: stc-red-team",
             ], "High"),
         ]},
    ]),

    Section(title="17. Backlog Summary", body=[
        {"type": "para", "text":
            "Everything above closes to the passing regression tests; "
            "14 epics, ~95 stories. This spec becomes the baseline for "
            "roadmap extensions (new epics STC-E16+ covering streaming, "
            "shadow-mode, chaos testing, etc. \u2014 see PRD section 9.2 "
            "and STAFF_REVIEW Tier-2)."},
    ]),
]


def main() -> None:
    build(
        DOCS_DIR / "STC_JIRA_Specification.docx",
        title="Jira Specification",
        subtitle="Epics, Stories, Acceptance Criteria",
        tagline="Reverse-engineered backlog for STC Framework v0.2.0",
        classification="INTERNAL",
        version="Version 1.0 \u2014 April 2026",
        doc_id="STC-JIRA-1.0",
        toc=[
            "Document Control",
            "Epic STC-E1 \u2014 Core Pipeline",
            "Epic STC-E2 \u2014 Sentinel Infrastructure",
            "Epic STC-E3 \u2014 Stalwart Execution",
            "Epic STC-E4 \u2014 Critic Governance",
            "Epic STC-E5 \u2014 Trainer Optimization",
            "Epic STC-E6 \u2014 Observability & Audit",
            "Epic STC-E7 \u2014 Governance & Subject Rights",
            "Epic STC-E8 \u2014 Production Safety",
            "Epic STC-E9 \u2014 Resilience",
            "Epic STC-E10 \u2014 Spec",
            "Epic STC-E11 \u2014 Adapter Layer",
            "Epic STC-E12 \u2014 Flask Service",
            "Epic STC-E13 \u2014 Supply Chain & CI",
            "Epic STC-E14 \u2014 Documentation",
            "Epic STC-E15 \u2014 Adversarial Testing",
            "Backlog Summary",
        ],
        sections=SECTIONS,
    )
    print("wrote STC_JIRA_Specification.docx")


if __name__ == "__main__":
    main()
