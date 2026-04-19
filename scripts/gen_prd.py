"""Reverse-engineered STC Framework Product Requirements Document."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from docgen import Section, build  # noqa: E402

DOCS_DIR = Path("C:/Projects/stc-framework/docs")

SECTIONS: list[Section] = [
    Section(title="1. Document Control", body=[
        {"type": "kv", "rows": [
            ("Product", "STC Framework"),
            ("Document type", "Product Requirements Document (PRD)"),
            ("Document ID", "STC-PRD-1.0"),
            ("Version", "1.0 \u2014 April 2026 (reverse-engineered)"),
            ("Status", "Approved for implementation (retroactive)"),
            ("Author", "Nitesh Ambastha"),
            ("Reviewers", "CISO, CDO, Head of Platform, Compliance, Legal"),
            ("Target release", "v0.2.0 (shipped)"),
        ]},
        {"type": "callout",
         "label": "About this document",
         "text":
            "This PRD was reverse-engineered from the v0.2.0 codebase "
            "and the six audit-suite regressions (test_security, "
            "test_privacy, test_observability, test_enterprise, "
            "test_staff_review, test_staff_review_round2). Every "
            "requirement listed is backed by a passing test. Treat this "
            "as the canonical product spec going forward; new features "
            "extend this document.",
         "color": "DBEAFE"},
    ]),
    Section(title="2. Problem Statement", body=[
        {"type": "sub", "title": "2.1 The Market Gap", "body": [
            {"type": "para", "text":
                "Enterprise AI agent adoption is bottlenecked by "
                "governance, not capability. Frameworks optimise for "
                "\"one agent that does everything\"; regulated "
                "environments require separation of duties, "
                "tamper-evident audit, provable data sovereignty, and "
                "granular tenant controls. Existing frameworks bolt "
                "these on as middleware, leaving compliance teams to "
                "audit half-built controls under deadline pressure."},
        ]},
        {"type": "sub", "title": "2.2 User Pain Points", "body": [
            {"type": "grid",
             "headers": ["User type", "Pain", "How STC addresses it"],
             "rows": [
                 ["Platform engineer", "Agents that work in dev fail in prod under cost / latency / safety regressions", "Observability by default; budget + rate limit + circuit breaker"],
                 ["Compliance officer", "Cannot map code to regulation line-by-line", "Declarative spec + 26-event audit catalogue + regulatory crosswalk"],
                 ["Security lead", "Audit log is a text file that anyone can edit", "HMAC-chained tamper-evident log + WORM pairing + signed spec"],
                 ["Data protection officer", "GDPR Art. 17 erasure is a one-off script every time", "governance.erase_tenant walks every store; DSAR export; stc-governance CLI"],
                 ["SRE", "Pods silently serve traffic into dead dependencies", "Deep /readyz with per-adapter probes; fail-fast startup"],
                 ["Product manager", "Cannot trust their own agent's numbers", "Numerical accuracy validator + citation required rail"],
             ]},
        ]},
        {"type": "sub", "title": "2.3 Why Now", "body": [
            {"type": "bullets", "items": [
                "EU AI Act enters enforcement phase 2026\u20132027. Regulators expect controllable, auditable AI.",
                "SEC is testing AI-agent deployments in broker-dealer contexts (17a-4 applies).",
                "GDPR Art. 17 enforcement precedents expanding to AI-generated content.",
                "Cost-DDoS against GPT/Claude-class APIs is an observed attack pattern.",
            ]},
        ]},
    ]),
    Section(title="3. Goals & Non-Goals", body=[
        {"type": "sub", "title": "3.1 Goals", "body": [
            {"type": "bullets", "items": [
                "G1 \u2014 Ship an AI-agent framework that passes regulated audit without wrappers.",
                "G2 \u2014 Separation of duties enforced by architecture, not by convention.",
                "G3 \u2014 Data sovereignty provable at three layers (spec, routing, dispatch).",
                "G4 \u2014 Audit log that survives adversarial write access.",
                "G5 \u2014 GDPR / CCPA / HIPAA / FINRA / SEC 17a-4 primitives built in.",
                "G6 \u2014 Zero-install defaults so a developer can go from pip install to working demo in under 2 minutes.",
                "G7 \u2014 Optional adapter layer so customers bring their own LLM / vector store / audit sink without forking.",
            ]},
        ]},
        {"type": "sub", "title": "3.2 Non-Goals", "body": [
            {"type": "bullets", "items": [
                "NG1 \u2014 Ship a model. STC is infra; LLMs are adapters.",
                "NG2 \u2014 Replace Langfuse / Arize / Kong. STC integrates with these; it is not a competitor.",
                "NG3 \u2014 Multi-language SDK (v1). Python-only for v0.x; evaluate JS / Java later.",
                "NG4 \u2014 Self-contained RLHF training. Agent Lightning optional; STC supplies the traces.",
                "NG5 \u2014 End-user-facing UI. STC is a library + a reference Flask service; chat UIs are out of scope.",
            ]},
        ]},
    ]),
    Section(title="4. Personas & Use Cases", body=[
        {"type": "sub", "title": "4.1 Primary Personas", "body": [
            {"type": "grid",
             "headers": ["Persona", "Role", "Primary success metric"],
             "rows": [
                 ["Platform Engineer", "Integrates STC into their product", "Time-to-first-query < 2 min; p95 overhead < 50ms"],
                 ["Compliance Officer", "Audits for regulator", "Can answer 'did we comply with Art. 17 on 2026-01-15?' from audit alone"],
                 ["Security Lead", "Owns cyber posture", "Tamper-evident log + adversarial probe suite pass 100% critical"],
                 ["SRE", "Keeps it running", "/readyz is honest; graceful shutdown on every SIGTERM"],
                 ["Product Manager", "Owns agent quality", "Hallucination rate < 2%; cost per tenant tracked"],
                 ["Data Engineer", "Governs data flows", "DSAR + erasure commands single-command; lineage provable"],
             ]},
        ]},
        {"type": "sub", "title": "4.2 Primary Use Cases", "body": [
            {"type": "numbered", "items": [
                "UC1 \u2014 Regulated financial Q&A over SEC filings with numerical accuracy and citation requirements.",
                "UC2 \u2014 Healthcare information retrieval with HIPAA-grade PHI redaction.",
                "UC3 \u2014 Internal knowledge-base agent with per-tenant isolation across business units.",
                "UC4 \u2014 Customer-facing AI assistant with budget caps preventing runaway cost per free-tier user.",
                "UC5 \u2014 Legal document assistance with signed-spec audit for discovery defensibility.",
            ]},
        ]},
    ]),
    Section(title="5. Functional Requirements", body=[
        {"type": "sub", "title": "5.1 Core Pipeline", "body": [
            {"type": "grid",
             "headers": ["Req ID", "Requirement", "Evidence"],
             "rows": [
                 ["FR-001", "Async aquery(query, tenant_id, idempotency_key) entry point", "system.py::aquery"],
                 ["FR-002", "Ten-step defensive pipeline executed in stable order", "Documented in system.py module docstring"],
                 ["FR-003", "Sync facade STCSystem.query refuses to run inside a running event loop", "test_system.py"],
                 ["FR-004", "Stalwart executes classify \u2192 retrieve \u2192 reason", "stalwart/agent.py"],
                 ["FR-005", "Critic validates input rails before LLM spend", "test_privacy.py::TestAuditCoverage"],
                 ["FR-006", "Critic validates output rails before response delivery", "critic/critic.py::aevaluate_output"],
                 ["FR-007", "Trainer observes traces and adjusts routing / prompts without direct runtime mutation", "trainer/*"],
             ]},
        ]},
        {"type": "sub", "title": "5.2 Compliance & Audit", "body": [
            {"type": "grid",
             "headers": ["Req ID", "Requirement", "Evidence"],
             "rows": [
                 ["FR-101", "Every query emits a query_accepted audit record", "test_privacy.py"],
                 ["FR-102", "Every rail failure emits a rail_failed audit record", "test_privacy.py"],
                 ["FR-103", "Every LLM call emits an llm_call audit record with cost, tokens, data_tier, boundary_crossing", "test_observability.py"],
                 ["FR-104", "Every audit record carries an HMAC-SHA256 entry_hash bound to the previous record", "test_staff_review_round2.py::TestHMACChain"],
                 ["FR-105", "verify_chain detects truncation, content tampering, and wrong-key forgery", "test_staff_review_round2.py"],
                 ["FR-106", "WORMAuditBackend refuses erase_tenant and prune_before", "test_staff_review_round2.py::TestWORMBackend"],
                 ["FR-107", "Ed25519 signed spec verified at startup in prod", "test_staff_review_round2.py::TestSpecSignature"],
                 ["FR-108", "26-event AuditEvent catalogue", "governance/events.py"],
                 ["FR-109", "Per-event-class retention policies", "test_staff_review_round2.py::TestPerEventRetention"],
             ]},
        ]},
        {"type": "sub", "title": "5.3 Data Sovereignty", "body": [
            {"type": "grid",
             "headers": ["Req ID", "Requirement", "Evidence"],
             "rows": [
                 ["FR-201", "Data classification into public / internal / restricted on every query", "sentinel/classifier.py"],
                 ["FR-202", "Restricted-tier data routed only to local / VPC models", "test_security.py::TestDataSovereigntyEnforcement"],
                 ["FR-203", "Three-layer enforcement: spec load, routing mutation, dispatch", "test_security.py"],
                 ["FR-204", "Boundary crossings always audited", "test_privacy.py"],
                 ["FR-205", "Presidio PII redaction before every LLM call", "sentinel/redaction.py"],
                 ["FR-206", "Retrieved chunks redacted before context assembly", "test_privacy.py::TestPIILeakSurface"],
                 ["FR-207", "HMAC-keyed surrogate tokenization available for restricted-tier data", "sentinel/tokenization.py"],
             ]},
        ]},
        {"type": "sub", "title": "5.4 Subject Rights", "body": [
            {"type": "grid",
             "headers": ["Req ID", "Requirement", "Evidence"],
             "rows": [
                 ["FR-301", "DSAR export returns all tenant-scoped data as a single JSON", "test_privacy.py::TestDSAR"],
                 ["FR-302", "Right-to-erasure removes tenant data from 7 stores (audit, history, vectors, tokens, idempotency, budget, RL)", "test_staff_review_round2.py::TestIdempotencyClearedOnErase"],
                 ["FR-303", "DSAR and erasure calls are themselves audited", "test_privacy.py"],
                 ["FR-304", "Erasure receipt retained for 6 years (does not itself erase)", "retention policy"],
                 ["FR-305", "CLI exposes verify-chain, dsar, erase, retention", "test_staff_review.py::TestGovernanceCLI"],
             ]},
        ]},
        {"type": "sub", "title": "5.5 Security Controls", "body": [
            {"type": "grid",
             "headers": ["Req ID", "Requirement", "Evidence"],
             "rows": [
                 ["FR-401", "16 prompt-injection rule families", "test_security.py::TestInjectionDetection"],
                 ["FR-402", "Zero-width / BiDi override normalisation on all input", "test_security.py::TestSanitizerInvariants"],
                 ["FR-403", "Header CR/LF/NUL stripping", "test_security.py::TestHeaderSanitization"],
                 ["FR-404", "Bounded-quantifier regex (ReDoS-safe) in redaction + injection rules", "test_security.py::TestReDoSHardening"],
                 ["FR-405", "Input size limits: query 8KB, chunk 8KB, context 120KB, request 64KB", "security/limits.py"],
                 ["FR-406", "Output-injection rail catches reflective attacks", "critic/validators/injection.py"],
             ]},
        ]},
        {"type": "sub", "title": "5.6 Production Safety", "body": [
            {"type": "grid",
             "headers": ["Req ID", "Requirement", "Evidence"],
             "rows": [
                 ["FR-501", "Per-tenant budget (daily + monthly) with atomic reserve/settle", "test_staff_review_round2.py::TestBudgetDayBuckets"],
                 ["FR-502", "Per-tenant token-bucket rate limiter with bounded memory", "test_staff_review.py::TestRateLimiter"],
                 ["FR-503", "Idempotency cache for safe client retries", "test_enterprise.py::TestIdempotency"],
                 ["FR-504", "Graceful shutdown with in-flight drain on SIGTERM", "test_enterprise.py::TestGracefulShutdown"],
                 ["FR-505", "Strict prod startup enforces 6 fail-closed invariants", "test_staff_review_round2.py::TestStrictProdMode"],
                 ["FR-506", "Deep /readyz probes every adapter", "test_observability.py::TestHealthProbe"],
                 ["FR-507", "Presidio warm-up at astart() eliminates cold-start penalty", "test_staff_review_round2.py::TestPresidioWarmup"],
             ]},
        ]},
        {"type": "sub", "title": "5.7 Observability", "body": [
            {"type": "grid",
             "headers": ["Req ID", "Requirement", "Evidence"],
             "rows": [
                 ["FR-601", "17 Prometheus metrics with bounded cardinality via tenant_label()", "test_observability.py"],
                 ["FR-602", "OpenTelemetry root span stc.aquery per query with child spans per stage", "test_observability.py::TestCorrelationBinding"],
                 ["FR-603", "Structured JSON logs with trace_id, span_id, tenant_id, persona auto-bound", "config/logging.py"],
                 ["FR-604", "Per-stage latency histogram (input_rails, stalwart, output_rails)", "test_observability.py"],
                 ["FR-605", "PII-safe log filter drops content fields unless STC_LOG_CONTENT=true", "config/logging.py"],
             ]},
        ]},
        {"type": "sub", "title": "5.8 Extensibility", "body": [
            {"type": "grid",
             "headers": ["Req ID", "Requirement", "Evidence"],
             "rows": [
                 ["FR-701", "LLM adapter Protocol with 2+ reference implementations (mock, litellm)", "adapters/llm/"],
                 ["FR-702", "Vector store Protocol with 2+ implementations (in_memory, qdrant)", "adapters/vector_store/"],
                 ["FR-703", "Audit backend Protocol with 2+ implementations (jsonl, worm)", "adapters/audit_backend/"],
                 ["FR-704", "New validator = new file + spec entry + __init__ registration; no framework changes", "CONTRIBUTING.md Recipe 1"],
                 ["FR-705", "New event type = single enum addition", "CONTRIBUTING.md Recipe 3"],
             ]},
        ]},
    ]),
    Section(title="6. Non-Functional Requirements", body=[
        {"type": "grid",
         "headers": ["Category", "Requirement", "Target"],
         "rows": [
             ["Performance", "Framework overhead p95", "< 50 ms (excluding LLM)"],
             ["Performance", "First-token latency p95 with cloud LLM", "< 2,000 ms"],
             ["Performance", "Sustained QPS per 2-vCPU pod, mock LLM", "\u2265 500"],
             ["Availability", "SLO", "99.9% monthly"],
             ["Availability", "RPO (audit log)", "\u2264 5 min with cross-region replication"],
             ["Availability", "RTO", "\u2264 15 min cold region cutover"],
             ["Scalability", "Stateless scale-out per pod", "Linear to at least 50 pods"],
             ["Resource", "Per-pod base memory", "\u2264 600 MiB with Presidio"],
             ["Resource", "Cold start", "\u2264 2 s (sub-1s with Presidio warm)"],
             ["Security", "Audit tamper evidence", "HMAC-SHA256 per record; 100% of 5000+ records verifiable"],
             ["Security", "Adversarial probe pass rate", "\u2265 90% overall; 100% critical-severity"],
             ["Reliability", "Circuit breaker recovery", "30-second half-open probe; configurable"],
             ["Testability", "Code coverage", "\u2265 70% on core packages (currently 81.6%)"],
             ["Compatibility", "Python", "3.10, 3.11, 3.12"],
             ["Compatibility", "Operating systems", "Linux (primary), Windows (dev), macOS (dev)"],
         ]},
    ]),
    Section(title="7. Compliance Requirements", body=[
        {"type": "grid",
         "headers": ["Regulation / Framework", "Requirement", "Mechanism"],
         "rows": [
             ["GDPR Art. 15", "Right of access fulfilled within 30 days", "DSAR CLI + export API"],
             ["GDPR Art. 17", "Right to erasure fulfilled", "Erasure CLI + 7-store scrubbing"],
             ["GDPR Art. 25", "Privacy by design", "Defaults fail closed; PII redacted before LLM"],
             ["GDPR Art. 30", "Records of processing", "HMAC-chained audit, 26 event types"],
             ["GDPR Art. 32", "Security of processing", "See Security Architecture doc"],
             ["CCPA / CPRA", "Right to know / delete", "Same as GDPR 15/17"],
             ["HIPAA \u00a7164.312", "Audit / integrity / transmission security", "HMAC chain + verify_chain + TLS + data sovereignty"],
             ["SEC 17a-4(f)", "Electronic records WORM for 6 years", "WORMAuditBackend paired with S3 Object Lock"],
             ["FINRA 4511", "Retention 6 years for broker-dealer records", "RetentionPolicy defaults"],
             ["SOX \u00a7404", "Change controls", "Signed spec + audit of routing/prompt mutations"],
             ["AIUC-1", "All 6 domains", "See AIUC-1 crosswalk"],
         ]},
    ]),
    Section(title="8. Release Criteria", body=[
        {"type": "numbered", "items": [
            "All six audit test suites pass (test_security, test_privacy, test_observability, test_enterprise, test_staff_review, test_staff_review_round2).",
            "Coverage \u2265 70% on core packages (spec, critic, trainer, sentinel, resilience, observability, system.py).",
            "pip-audit --strict passes; CycloneDX SBOM artifact generated.",
            "CI secret scan passes.",
            "Adversarial probe suite: 100% critical-severity pass, \u2265 90% overall.",
            "STC_Framework_Architecture_and_Capabilities.docx reflects current shipped capabilities.",
            "CHANGELOG.md entry for every change under ## [Unreleased].",
            "Public API additions referenced in docs/ARCHITECTURE.md or docs/DECISIONS.md.",
        ]},
    ]),
    Section(title="9. Out-of-Scope & Roadmap", body=[
        {"type": "sub", "title": "9.1 Explicitly Out of Scope for v0.2.x", "body": [
            {"type": "bullets", "items": [
                "Multi-region active-active with shared state stores.",
                "Streaming LLM responses (SSE / WebSocket).",
                "Shadow-mode / canary deployment of prompt or routing changes.",
                "Feature-flag / kill-switch system.",
                "Multi-language SDKs (Python only).",
                "In-product chat UI."
            ]},
        ]},
        {"type": "sub", "title": "9.2 Tier-2 Roadmap", "body": [
            {"type": "para", "text":
                "Full roadmap in docs/security/STAFF_REVIEW.md. Highlights:"},
            {"type": "bullets", "items": [
                "S9 \u2014 Per-SystemContext DI to support multiple STCSystem instances in one process.",
                "S10 \u2014 Streaming LLM responses with rail-on-partial-text semantics.",
                "S11 \u2014 Shadow-mode for prompt rollouts (run, record, don't enforce).",
                "S12 \u2014 Env-driven feature flags / kill switches for incident response.",
                "S13 \u2014 Chaos test harness (failure injection, clock skew, disk full).",
                "S14 \u2014 Performance benchmark regression gates in CI.",
                "S15 \u2014 Public API stability annotations (@public vs @experimental).",
                "S16 \u2014 Config hot-reload.",
                "S17 \u2014 Multi-region shared-state adapters (Redis, Postgres).",
                "S18 \u2014 LLM model-drift / output-fingerprint detection.",
            ]},
        ]},
    ]),
    Section(title="10. Success Metrics", body=[
        {"type": "grid",
         "headers": ["Metric", "Target (first 12 months post-launch)"],
         "rows": [
             ["Regulated enterprise deployments", "\u2265 5"],
             ["Third-party audit passes", "\u2265 2 (SOC 2 Type II, ISO 27001, or equivalent)"],
             ["Security incidents rooted in framework", "0 P0; \u2264 2 P1"],
             ["Mean time to add a new rail", "\u2264 2 hours for a junior engineer (CONTRIBUTING Recipe 1 time)"],
             ["Hallucination rate in reference Financial Q&A", "< 2%"],
             ["Adversarial probe pass rate (critical)", "100%"],
             ["Framework-overhead p95", "< 50 ms"],
         ]},
    ]),
]


def main() -> None:
    build(
        DOCS_DIR / "STC_Product_Requirements_Document.docx",
        title="Product Requirements Document",
        subtitle="STC Framework",
        tagline="Reverse-engineered v1.0 \u2014 what the product is and why it exists",
        classification="INTERNAL",
        version="Version 1.0 \u2014 April 2026",
        doc_id="STC-PRD-1.0",
        toc=[
            "Document Control",
            "Problem Statement",
            "Goals & Non-Goals",
            "Personas & Use Cases",
            "Functional Requirements",
            "Non-Functional Requirements",
            "Compliance Requirements",
            "Release Criteria",
            "Out-of-Scope & Roadmap",
            "Success Metrics",
        ],
        sections=SECTIONS,
    )
    print("wrote STC_Product_Requirements_Document.docx")


if __name__ == "__main__":
    main()
