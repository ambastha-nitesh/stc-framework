"""Regenerate STC_Framework_Architecture_and_Capabilities.docx."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from docgen import Section, build, session_changes_callout  # noqa: E402


DOCS_DIR = Path("C:/Projects/stc-framework/docs")


SECTIONS: list[Section] = [
    Section(
        title="1. Executive Summary",
        body=[
            session_changes_callout(),
            {"type": "sub", "title": "1.1 Thesis", "body": [
                {"type": "para", "text":
                    "Most AI agent frameworks ship a single agent with system prompts "
                    "for different modes. That design fails regulated audit: the "
                    "same code path that answers a question also evaluates its own "
                    "answer, also decides whether to self-retrain, also holds the "
                    "keys. STC separates these concerns into four architectural "
                    "planes with asymmetric authority enforced by module boundaries "
                    "and driven by a signed declarative spec. The result is an "
                    "agent architecture that a regulator can certify and a "
                    "security team can operate."},
            ]},
            {"type": "sub", "title": "1.2 The Three Personas + Sentinel", "body": [
                {"type": "grid",
                 "headers": ["Persona", "Plane", "Responsibility", "Cannot"],
                 "rows": [
                     ["Stalwart", "Execution", "Run the business task (classify \u2192 retrieve \u2192 reason)", "Evaluate its own output"],
                     ["Trainer", "Optimization", "Observe traces, adjust prompts & routing", "Mutate runtime state directly"],
                     ["Critic", "Governance", "Verify every response, enforce rails, escalate", "Rewrite responses"],
                     ["Sentinel", "Infrastructure", "Classify, redact, tokenize, route, audit", "Run business logic"],
                 ]},
            ]},
            {"type": "sub", "title": "1.3 April 2026 Hardening Snapshot", "body": [
                {"type": "para", "text":
                    "The framework now ships with enterprise readiness posture "
                    "suitable for FINRA / SEC / HIPAA / GDPR regulated "
                    "environments. Highlights below; full details in sections 5, "
                    "6, 8 and 11."},
                {"type": "bullets", "items": [
                    "HMAC-SHA256 hash-chained audit log (tamper-evident against adversarial write access, not just bit-rot).",
                    "WORM-compatible audit backend refuses erase / prune with ComplianceViolation for SEC 17a-4 deployments.",
                    "Ed25519 signed declarative spec verified at startup.",
                    "Strict production mode enforces six fail-closed invariants at astart().",
                    "Per-event-class retention policies (erasure receipts 6 years; chain seals forever).",
                    "Per-tenant rolling-bucket budget with monotonic-clock safety check.",
                    "Idempotency cache cleared on right-to-erasure to prevent resurfacing of erased data.",
                    "255 regression tests across 6 audit suites; 81.6% coverage.",
                ]},
            ]},
        ],
    ),
    Section(
        title="2. System Architecture",
        body=[
            {"type": "sub", "title": "2.1 Four Architectural Planes", "body": [
                {"type": "para", "text":
                    "The call graph between planes is constrained by module "
                    "boundaries. Stalwart calls only Sentinel. Critic reads any "
                    "Stalwart output but cannot call Stalwart. Trainer writes "
                    "only via Sentinel and PromptRegistry. Sentinel talks only "
                    "to adapter Protocols. A PR that introduces a new "
                    "inter-plane arrow without audit instrumentation is a "
                    "compliance regression."},
            ]},
            {"type": "sub", "title": "2.2 Request Flow (happy path)", "body": [
                {"type": "numbered", "items": [
                    "STCSystem.aquery receives (query, tenant_id, idempotency_key).",
                    "Input sanitisation: type, size, Unicode normalisation, header cleaning.",
                    "Idempotency cache check; if hit, return cached result.",
                    "Shutdown flag, degradation state, tenant rate-limit, tenant budget reservation.",
                    "Correlation context bound (trace_id, request_id, tenant_id, persona).",
                    "Critic input rails run; on critical failure the query is blocked before LLM spend.",
                    "Stalwart: classify data tier, embed query, search vector store (tenant-filtered), redact retrieved chunks, assemble context.",
                    "Sentinel gateway: final PII redaction, optional surrogate tokenization, model selection per data tier, retry + circuit + timeout + bulkhead + fallback chain.",
                    "Critic output rails run; numerical / hallucination / scope / PII / citation / toxicity / output-injection.",
                    "Audit emit query_completed, metrics increment, budget settle, correlation unbind.",
                ]},
            ]},
            {"type": "sub", "title": "2.3 Defence-in-Depth", "body": [
                {"type": "grid",
                 "headers": ["Layer", "Mechanism", "Implementation"],
                 "rows": [
                     ["1. Input rails", "Injection / scope / PII-in detection", "critic/validators/injection.py + scope.py + pii.py"],
                     ["2. Input sanitisation", "Unicode, zero-width, header controls", "security/sanitize.py"],
                     ["3. Size limits", "Query, chunk, context, header, body caps", "security/limits.py"],
                     ["4. Data tier + PII redaction", "Presidio + spec-declared patterns", "sentinel/classifier.py + redaction.py"],
                     ["5. Chunk redaction", "Indirect PII defence", "stalwart/agent.py::_retrieve"],
                     ["6. Routing policy", "3-layer restricted-tier enforcement", "spec/models.py + sentinel/gateway.py"],
                     ["7. Output rails", "Hallucination, citation, output-injection", "critic/validators/*.py"],
                     ["8. Escalation state machine", "NORMAL \u2192 DEGRADED \u2192 QUARANTINE \u2192 PAUSED", "resilience/degradation.py"],
                 ]},
            ]},
        ],
    ),
    Section(
        title="3. Sentinel Layer \u2014 Modules",
        body=[
            {"type": "sub", "title": "3.1 Data Classifier", "body": [
                {"type": "para", "text":
                    "Presidio-based entity detection augmented with spec-declared "
                    "custom patterns (account number regex, advisor code, client "
                    "portfolio keywords). Every query is classified into one of "
                    "public / internal / restricted before the gateway selects a "
                    "model."},
            ]},
            {"type": "sub", "title": "3.2 PII Redactor", "body": [
                {"type": "para", "text":
                    "Bounded-quantifier regex patterns (ReDoS-safe) plus Presidio "
                    "analyzer. Entities configured in the spec as MASK or BLOCK; "
                    "BLOCK entities raise DataSovereigntyViolation instead of "
                    "being silently passed. Runs on both user input and retrieved "
                    "chunks (indirect-PII defence)."},
            ]},
            {"type": "sub", "title": "3.3 Tokenizer + Token Store", "body": [
                {"type": "para", "text":
                    "HMAC-SHA256 surrogate tokenization. Tokens of form "
                    "STC_TOK_<12hex> are reversible via an AES-GCM encrypted "
                    "file store (mode 0o600 on POSIX, atomic O_NOFOLLOW write). "
                    "Tokens carry tenant_id + created_at so right-to-erasure and "
                    "retention can target them."},
            ]},
            {"type": "sub", "title": "3.4 Gateway + Routing", "body": [
                {"type": "para", "text":
                    "Async LLM gateway with per-downstream circuit breaker, "
                    "tenacity retry with full-jitter exponential backoff, "
                    "asyncio.timeout (3.11+) or wait_for shim (3.10), "
                    "asyncio.Semaphore bulkhead, and declarative fallback chain. "
                    "Restricted-tier routing enforced at three points: spec "
                    "load, set_routing_preference, and dispatch."},
            ]},
            {"type": "sub", "title": "3.5 Virtual Key Manager + MCP Policy", "body": [
                {"type": "para", "text":
                    "Per-persona virtual keys with scope-bounded permissions. "
                    "MCP access policy defaults to deny; spec's trusted_agents "
                    "and mcp_access_policy arrays declare explicit allows."},
            ]},
        ],
    ),
    Section(
        title="4. Core Personas",
        body=[
            {"type": "sub", "title": "4.1 Stalwart \u2014 Execution", "body": [
                {"type": "para", "text":
                    "Async RAG pipeline: classify \u2192 retrieve \u2192 assemble "
                    "\u2192 reason \u2192 format. Vector search filtered by "
                    "tenant_id. Chunks run through PIIRedactor before context "
                    "assembly. Exception messages replaced with exception class "
                    "name only to prevent PII leakage via error paths. Per-stage "
                    "latency histogram (stc_stage_latency_ms)."},
            ]},
            {"type": "sub", "title": "4.2 Trainer \u2014 Optimization", "body": [
                {"type": "para", "text":
                    "Observes traces via AuditLogger and trainer history store. "
                    "RoutingController applies model-order changes via Sentinel; "
                    "PromptController rotates prompts via registry. "
                    "TenantBudgetTracker uses UTC calendar-day buckets "
                    "(35-day ring, O(1) per op, monotonic clock sanity check). "
                    "MaintenanceExecutor drives DegradationState based on cost, "
                    "accuracy, and hallucination-rate triggers."},
            ]},
            {"type": "sub", "title": "4.3 Critic \u2014 Zero-Trust Governance", "body": [
                {"type": "para", "text":
                    "Eight built-in validators: prompt_injection_detection, "
                    "numerical_accuracy, hallucination_detection, "
                    "investment_advice_detection, scope_check, pii_output_scan, "
                    "toxicity_check, output_injection_scan, citation_required. "
                    "EscalationManager implements a four-state machine with "
                    "consecutive-failure circuit breaker and cooldown. Each "
                    "rail emits a rail_failed audit event on failure."},
                {"type": "grid",
                 "headers": ["Rail", "Severity", "Purpose"],
                 "rows": [
                     ["numerical_accuracy", "critical", "Blocks numerical claims not grounded in source"],
                     ["hallucination_detection", "critical", "Sentence-level grounding score"],
                     ["citation_required", "high", "Numerical claims must carry [Source: ...]"],
                     ["pii_output_scan", "critical", "No PII in response"],
                     ["investment_advice_detection", "high", "Blocks buy/sell/hold recommendations"],
                     ["scope_check", "low", "Warns on out-of-scope topics"],
                     ["toxicity_check", "medium", "Heuristic / NeMo-backed toxicity"],
                     ["prompt_injection_detection", "critical", "Input rail for injection patterns"],
                     ["output_injection_scan", "critical", "Output rail for reflected injection"],
                 ]},
            ]},
        ],
    ),
    Section(
        title="5. Observability & Audit",
        body=[
            {"type": "sub", "title": "5.1 HMAC-Chained Audit", "body": [
                {"type": "para", "text":
                    "Every AuditRecord is sealed with HMAC-SHA256 keyed by "
                    "STC_AUDIT_HMAC_KEY and chained to the previous record's "
                    "entry_hash. key_id is stamped on every record so rotations "
                    "preserve verifiability. verify_chain accepts "
                    "accept_unknown_genesis=True for post-prune verification."},
                {"type": "callout",
                 "label": "Why HMAC, not SHA-256",
                 "text":
                    "Plain SHA-256 is a public hash. An attacker with write "
                    "access but no key can truncate the log, rewrite the new "
                    "first record's prev_hash to the genesis sentinel, and "
                    "recompute every subsequent entry_hash. The chain would "
                    "verify. HMAC requires a secret; without it, recomputation "
                    "fails verification.",
                 "color": "FEE2E2"},
            ]},
            {"type": "sub", "title": "5.2 Audit Backends", "body": [
                {"type": "grid",
                 "headers": ["Backend", "Use case", "erase_tenant", "prune_before"],
                 "rows": [
                     ["JSONLAuditBackend", "GDPR-primary deployments", "Supported (rewrites chain)", "Supported (writes seal)"],
                     ["WORMAuditBackend", "SEC 17a-4 / FINRA 4511", "ComplianceViolation", "ComplianceViolation"],
                 ]},
            ]},
            {"type": "sub", "title": "5.3 Metrics (Prometheus)", "body": [
                {"type": "grid",
                 "headers": ["Metric", "Type", "Labels"],
                 "rows": [
                     ["stc_queries_total", "counter", "persona, tenant, action"],
                     ["stc_latency_ms", "histogram", "persona, stage"],
                     ["stc_stage_latency_ms", "histogram", "stage"],
                     ["stc_cost_usd_total", "counter", "model, tenant"],
                     ["stc_guardrail_failures_total", "counter", "rail, severity"],
                     ["stc_governance_events_total", "counter", "event_type"],
                     ["stc_tenant_budget_usd", "gauge", "tenant, window"],
                     ["stc_tenant_budget_rejections_total", "counter", "tenant, window"],
                     ["stc_circuit_breaker_state", "gauge", "downstream"],
                     ["stc_escalation_level", "gauge", "\u2014"],
                     ["stc_redaction_events_total", "counter", "entity_type"],
                     ["stc_boundary_crossings_total", "counter", "from_tier, to_model"],
                     ["stc_bulkhead_rejections_total", "counter", "bulkhead"],
                     ["stc_retry_attempts_total", "counter", "downstream, outcome"],
                     ["stc_adapter_healthcheck", "gauge", "adapter"],
                     ["stc_inflight_requests", "gauge", "\u2014"],
                     ["stc_system_info", "gauge", "service_version, spec_version, env"],
                 ]},
            ]},
            {"type": "sub", "title": "5.4 Correlation via ContextVar", "body": [
                {"type": "para", "text":
                    "trace_id, request_id, tenant_id, persona, prompt_version "
                    "flow through contextvars.ContextVar instances. Every "
                    "structured log line and every OpenTelemetry span reads "
                    "from the same snapshot, so log \u2194 trace \u2194 audit "
                    "pivots work end-to-end without threading values through "
                    "every function signature."},
            ]},
            {"type": "sub", "title": "5.5 Governance CLI", "body": [
                {"type": "para", "text":
                    "The stc-governance CLI exposes four operator commands: "
                    "verify-chain, dsar, erase (requires --yes), retention. "
                    "Installed as a pyproject entry point for runbooks and "
                    "scheduled jobs."},
            ]},
        ],
    ),
    Section(
        title="6. Production Safety & Enterprise Readiness",
        body=[
            {"type": "sub", "title": "6.1 Strict Production Mode Invariants", "body": [
                {"type": "para", "text":
                    "STC_ENV=prod enforces six fail-closed checks at astart(). "
                    "A missing or wrong value raises STCError; the Kubernetes "
                    "readiness probe fails and the pod never enters the pool."},
                {"type": "numbered", "items": [
                    "STC_AUDIT_HMAC_KEY is set (no ephemeral audit key).",
                    "STC_TOKENIZATION_STRICT=1 (missing tokenization key fails closed).",
                    "STC_LOG_CONTENT=false (no request bodies in logs).",
                    "STC_LLM_ADAPTER != \"mock\" (no accidental mock LLM in prod).",
                    "STC_AUDIT_BACKEND=worm (WORM-shaped audit backend).",
                    "Ed25519 spec signature verifies against STC_SPEC_PUBLIC_KEY.",
                ]},
            ]},
            {"type": "sub", "title": "6.2 Per-Tenant Budget", "body": [
                {"type": "para", "text":
                    "TenantBudgetTracker aggregates costs into UTC calendar-day "
                    "buckets (35-day ring). reserve() is atomic with enforce() "
                    "to close the TOCTOU race where concurrent requests both "
                    "pass a plain enforce+record_cost. Monotonic clock "
                    "cross-check emits a warning on backward jumps. Refunds on "
                    "crash and input-rail block paths so tenants are never "
                    "billed for failed requests."},
            ]},
            {"type": "sub", "title": "6.3 Rate Limit + Idempotency", "body": [
                {"type": "para", "text":
                    "TenantRateLimiter is a per-tenant token bucket bounded by "
                    "max_tenants (LRU eviction) to prevent memory blow-up at "
                    "scale. IdempotencyCache is LRU + TTL keyed by (tenant_id, "
                    "idempotency_key) so retries return cached QueryResult "
                    "without re-charging the tenant or emitting duplicate "
                    "audits. Both cleared on right-to-erasure."},
            ]},
            {"type": "sub", "title": "6.4 Graceful Shutdown", "body": [
                {"type": "para", "text":
                    "SIGTERM triggers runner.shutdown(drain_timeout=30). The "
                    "_stopping flag rejects new requests. InflightTracker "
                    "waits for pending queries to finish. Adapters close via "
                    "aclose() in dependency order. Audit closes last. "
                    "Kubernetes terminationGracePeriodSeconds must be \u2265 35s."},
            ]},
            {"type": "sub", "title": "6.5 Supply Chain", "body": [
                {"type": "para", "text":
                    "CI pipeline includes pip-audit CVE scan, CycloneDX SBOM "
                    "artifact, and regex-based secret scan (AWS keys, OpenAI "
                    "keys, Slack tokens, private keys). New top-level "
                    "dependencies require review."},
            ]},
        ],
    ),
    Section(
        title="7. Data Sovereignty",
        body=[
            {"type": "sub", "title": "7.1 Tiered Data Classification", "body": [
                {"type": "grid",
                 "headers": ["Tier", "Criteria", "Allowed models (example)"],
                 "rows": [
                     ["public", "No sensitive data", "cloud + VPC + local"],
                     ["internal", "PII but not high-risk", "VPC + local"],
                     ["restricted", "Credit card / SSN / bank / custom", "local only (Ollama / vLLM / Bedrock-VPC)"],
                 ]},
            ]},
            {"type": "sub", "title": "7.2 Three-Layer Enforcement", "body": [
                {"type": "numbered", "items": [
                    "Spec load: routing_policy.restricted must contain only local models (validated in spec/models.py).",
                    "Runtime mutation: set_routing_preference refuses cloud models in the restricted tier.",
                    "Dispatch: acompletion re-checks and raises DataSovereigntyViolation if any non-local model appears in the restricted candidate list.",
                ]},
            ]},
            {"type": "sub", "title": "7.3 Surrogate Tokenization", "body": [
                {"type": "para", "text":
                    "For restricted-tier data that must pass through cloud "
                    "models (when explicitly declared), HMAC-keyed surrogate "
                    "tokens replace sensitive values. The response is "
                    "detokenized in-process; tokens carry tenant_id and "
                    "created_at for erasure and retention."},
            ]},
        ],
    ),
    Section(
        title="8. Regulatory & Compliance Alignment",
        body=[
            {"type": "grid",
             "headers": ["Regulation / Framework", "Implementation"],
             "rows": [
                 ["SEC 17a-4(f) / FINRA 4511", "WORMAuditBackend + 6-year audit retention defaults"],
                 ["GDPR Art. 5(1)(c) data minimisation", "record_from_trace filters user content; Notifier strips PII"],
                 ["GDPR Art. 5(1)(e) storage limitation", "apply_retention per-event-class"],
                 ["GDPR Art. 15 right of access", "export_tenant_records \u2192 DSAR record"],
                 ["GDPR Art. 17 right to erasure", "erase_tenant across audit / history / vector / tokens / idempotency / budget / RL"],
                 ["GDPR Art. 30 records of processing", "26-event AuditEvent catalogue + HMAC chain"],
                 ["HIPAA \u00a7164.312(b) audit controls", "Append-only HMAC-chained log"],
                 ["HIPAA \u00a7164.312(c) integrity", "verify_chain detects tampering"],
                 ["SOC 2 CC7.2 / CC7.3 logging", "Exhaustive audit + governance metrics"],
                 ["SOC 2 CC8.1 change management", "prompt_registered + routing_updated audit events + signed spec"],
                 ["AIUC-1 A001\u2013A007", "Sentinel, tokenization, classification, virtual keys"],
                 ["AIUC-1 B adversarial robustness", "test_security.py + adversarial probes"],
                 ["AIUC-1 E audit trail", "HMAC-chained immutable log"],
                 ["NYDFS Part 500 \u00a7500.17", "Incident-response procedure in runbook"],
             ]},
        ],
    ),
    Section(
        title="9. Technology Stack",
        body=[
            {"type": "grid",
             "headers": ["Capability", "Tool", "License", "Role"],
             "rows": [
                 ["Agent execution", "LangGraph", "MIT", "Optional Stalwart workflow"],
                 ["RL optimisation", "Agent Lightning", "MIT", "Optional Trainer bridge"],
                 ["LLM gateway", "LiteLLM", "Apache 2.0", "Default gateway + routing"],
                 ["Runtime firewall", "Meta LlamaFirewall", "MIT", "Optional prompt firewall"],
                 ["Guardrails", "NeMo + Guardrails AI", "Apache 2.0", "External guardrail orchestration"],
                 ["PII detection", "Microsoft Presidio", "MIT", "Entity detection + redaction"],
                 ["Audit integrity", "HMAC-SHA256 chain", "Built-in", "Tamper-evident log"],
                 ["Spec signing", "ed25519 (cryptography)", "BSD", "Signed declarative spec"],
                 ["WORM storage pairing", "S3 Object Lock / Immudb", "External", "OS-level immutability"],
                 ["Prompt registry", "Langfuse (file default)", "MIT", "Versioned prompts"],
                 ["Observability", "OpenTelemetry + Prometheus", "Apache 2.0", "Traces + 17 metrics"],
                 ["Vector store", "Qdrant (in-memory default)", "Apache 2.0", "Tenant-filtered search"],
                 ["Local LLM", "Ollama", "MIT", "Restricted-tier inference"],
                 ["Resilience", "tenacity + pybreaker", "Apache 2.0", "Retry + circuit + bulkhead"],
                 ["Structured logs", "structlog", "MIT / Apache", "PII-safe log filter"],
                 ["Supply-chain", "pip-audit + CycloneDX", "Apache 2.0", "CI CVE + SBOM"],
             ]},
        ],
    ),
    Section(
        title="10. Getting Started",
        body=[
            {"type": "sub", "title": "10.1 Install", "body": [
                {"type": "code", "code":
                    "pip install -e .[dev,service,langgraph]\n"
                    "pre-commit install"},
            ]},
            {"type": "sub", "title": "10.2 Run the full test battery", "body": [
                {"type": "code", "code":
                    "PYTHONPATH=src pytest tests/ \\\n"
                    "  --cov=src/stc_framework --cov-fail-under=70"},
            ]},
            {"type": "sub", "title": "10.3 Run the Flask service locally", "body": [
                {"type": "code", "code":
                    "pip install -e .[service]\n"
                    "gunicorn -k gthread --threads 8 -w 4 \\\n"
                    "  --bind 0.0.0.0:8000 \\\n"
                    "  'stc_framework.service.wsgi:application'"},
            ]},
            {"type": "sub", "title": "10.4 Governance CLI examples", "body": [
                {"type": "code", "code":
                    "stc-governance verify-chain /mnt/audit\n"
                    "stc-governance dsar acme-corp --output dsar.json\n"
                    "stc-governance erase acme-corp --yes\n"
                    "stc-governance retention"},
            ]},
            {"type": "sub", "title": "10.5 Related documents", "body": [
                {"type": "bullets", "items": [
                    "STC_Security_Architecture.docx \u2014 threat model, controls, incident response.",
                    "STC_Data_Governance_Framework.docx \u2014 DSAR, erasure, retention, data minimisation.",
                    "STC_Cyber_Defense_Framework.docx \u2014 adversarial testing, pen tests, bug bounty.",
                    "STC_Enterprise_Architecture.docx \u2014 HA, scaling, resilience, deployment.",
                    "STC_Product_Requirements_Document.docx \u2014 product requirements (reverse-engineered).",
                    "STC_JIRA_Specification.docx \u2014 epics, stories, acceptance criteria.",
                    "STC_System_Design_Document.docx \u2014 module design, protocols, data model.",
                ]},
            ]},
        ],
    ),
]


def main() -> None:
    build(
        DOCS_DIR / "STC_Framework_Architecture_and_Capabilities.docx",
        title="Architecture, Design & Capabilities",
        subtitle="Stalwart \u00b7 Trainer \u00b7 Critic",
        tagline="Production-grade AI agent systems for regulated environments",
        classification="INTERNAL",
        version="Version 2.0 \u2014 April 2026",
        doc_id="STC-ARCH-2.0",
        toc=[
            "Executive Summary",
            "System Architecture",
            "Sentinel Layer \u2014 Modules",
            "Core Personas",
            "Observability & Audit",
            "Production Safety & Enterprise Readiness",
            "Data Sovereignty",
            "Regulatory & Compliance Alignment",
            "Technology Stack",
            "Getting Started",
        ],
        sections=SECTIONS,
    )
    print("wrote STC_Framework_Architecture_and_Capabilities.docx")


if __name__ == "__main__":
    main()
