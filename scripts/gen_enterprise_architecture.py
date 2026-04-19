"""Regenerate STC_Enterprise_Architecture.docx."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from docgen import Section, build, session_changes_callout  # noqa: E402

DOCS_DIR = Path("C:/Projects/stc-framework/docs")

SECTIONS: list[Section] = [
    Section(title="1. Purpose", body=[
        session_changes_callout(),
        {"type": "para", "text":
            "This document describes the enterprise architecture for "
            "running STC Framework in production. Audience: enterprise "
            "architects, SRE leads, platform engineering. Paired with "
            "the Security Architecture and Cyber Defense documents, it "
            "is the artifact an EA review board approves before a "
            "regulated deployment."},
    ]),
    Section(title="2. Deployment Topology", body=[
        {"type": "sub", "title": "2.1 Recommended Pod Layout", "body": [
            {"type": "grid",
             "headers": ["Component", "Deployment", "HA Guidance"],
             "rows": [
                 ["STCSystem (Flask service)", "Kubernetes Deployment", "3+ replicas across 3 AZs; HPA on stc_inflight_requests"],
                 ["LiteLLM gateway", "Kubernetes Deployment", "2+ replicas; Redis-backed for routing state"],
                 ["Presidio", "Sidecar or service", "Single instance per Flask pod (warmed at startup)"],
                 ["Qdrant", "StatefulSet", "3-node cluster with replication"],
                 ["Ollama (restricted-tier)", "StatefulSet / GPU pool", "Local-only; data sovereignty"],
                 ["Audit store (WORM)", "S3 Object Lock bucket / Immudb / equivalent", "Region-replicated with compliance-mode lock"],
                 ["Prometheus + OTel collector", "Cluster-wide", "Standard SRE practice"],
                 ["Langfuse", "Optional \u2014 Kubernetes Deployment + Postgres", "For versioned prompt registry"],
             ]},
        ]},
        {"type": "sub", "title": "2.2 Worker Sizing Formula", "body": [
            {"type": "para", "text":
                "Gunicorn with threaded workers is the supported mode. The "
                "Flask worker owns an asyncio event loop thread "
                "(_SystemRunner) for the STCSystem. Request threads "
                "submit to the loop and wait on futures. This means "
                "concurrency is driven by loop capacity, not thread "
                "count alone."},
            {"type": "kv", "rows": [
                ("-w (workers)", "1\u20132 per vCPU"),
                ("--threads per worker", "8\u201316 (bounded by STC_LLM_BULKHEAD)"),
                ("STC_LLM_BULKHEAD", "64\u2013128 for LLM-heavy workloads"),
                ("STC_VECTOR_BULKHEAD", "64\u2013128"),
                ("STC_EMBEDDING_BULKHEAD", "64\u2013128"),
                ("Memory per worker", "~300\u2013600 MiB base + Presidio; headroom for context"),
                ("terminationGracePeriodSeconds", "\u2265 35 (drain_timeout + 5)"),
            ]},
        ]},
    ]),
    Section(title="3. Scaling Strategy", body=[
        {"type": "sub", "title": "3.1 Horizontal Scaling Dimensions", "body": [
            {"type": "bullets", "items": [
                "Stateless: STCSystem instances hold in-memory state (singletons) but do not require sticky sessions \u2014 any pod can serve any tenant.",
                "Shared state: audit log is pod-local unless a shared backend (S3 Object Lock, Immudb, Postgres) is configured.",
                "History store: defaults to in-memory (per-pod); swap to SQLite / Postgres for cross-pod optimization.",
                "Rate-limit and budget tracking: pod-local by default; for strict cross-pod enforcement, plug in a Redis-backed tracker conforming to the TenantBudgetTracker / TenantRateLimiter protocols.",
            ]},
        ]},
        {"type": "sub", "title": "3.2 HPA / KEDA Signals", "body": [
            {"type": "grid",
             "headers": ["Signal", "Threshold (example)", "Action"],
             "rows": [
                 ["stc_inflight_requests", "> 75% of STC_LLM_BULKHEAD", "Scale up"],
                 ["stc_bulkhead_rejections_total (rate)", "> 0 for 2 min", "Scale up"],
                 ["stc_stage_latency_ms{stage=\"stalwart\"} p99", "> 3s for 5 min", "Scale up"],
                 ["CPU utilization", "> 70%", "Scale up (secondary)"],
                 ["stc_queries_total rate", "< 10% of baseline for 10 min", "Scale down cautiously"],
             ]},
        ]},
    ]),
    Section(title="4. Availability & Resilience", body=[
        {"type": "sub", "title": "4.1 Resilience Primitives", "body": [
            {"type": "grid",
             "headers": ["Primitive", "Failure it mitigates", "Configuration"],
             "rows": [
                 ["Retry with full-jitter exponential backoff", "Transient upstream (429, 5xx)", "STC_LLM_RETRY_MAX_ATTEMPTS=3"],
                 ["Per-downstream circuit breaker", "Sustained upstream outage", "STC_LLM_CIRCUIT_FAIL_MAX=5, STC_LLM_CIRCUIT_RESET_SEC=30"],
                 ["Async timeout", "Hung upstream", "STC_LLM_TIMEOUT_SEC=30"],
                 ["Bulkhead", "Slow upstream exhausting workers", "STC_LLM_BULKHEAD=64"],
                 ["Fallback chain", "Primary model down", "Declared in data_sovereignty.routing_policy[tier]"],
                 ["Degradation state machine", "Sustained rail failures", "critic.escalation.circuit_breaker"],
             ]},
        ]},
        {"type": "sub", "title": "4.2 Graceful Shutdown", "body": [
            {"type": "para", "text":
                "SIGTERM triggers runner.shutdown(drain_timeout=30). "
                "Sequence: _stopping=True rejects new requests \u2192 "
                "InflightTracker.wait_idle blocks on pending work \u2192 "
                "adapters close via aclose() in dependency order \u2192 "
                "audit log closes last. Kubernetes preStop hook is "
                "compatible \u2014 ensure terminationGracePeriodSeconds "
                "\u2265 35."},
        ]},
        {"type": "sub", "title": "4.3 Failure Modes & Responses", "body": [
            {"type": "grid",
             "headers": ["Failure", "Detection", "Action"],
             "rows": [
                 ["LLM provider outage", "stc_circuit_breaker_state{downstream=llm:*} == 2", "Fallback chain selects next model; if all fail, /readyz returns 503"],
                 ["Vector store down", "Circuit + keyword-search fallback", "Stalwart retrieval degrades to keyword search"],
                 ["Audit disk full", "stc_governance_events_total drops; OSError", "Audit-disk alert; operator intervention"],
                 ["Presidio mis-configured", "Startup warmup fails (logged)", "Regex fallback keeps redaction working"],
                 ["Spec signature invalid at startup", "STCError", "Pod fails readiness; image re-check"],
             ]},
        ]},
    ]),
    Section(title="5. Performance", body=[
        {"type": "sub", "title": "5.1 Latency Budget Example (p95 target)", "body": [
            {"type": "grid",
             "headers": ["Stage", "Budget (ms)", "Notes"],
             "rows": [
                 ["Input rails", "25", "Bulkhead 128; regex-only validators"],
                 ["Embedding", "50", "Ollama local; Qdrant search <10ms"],
                 ["Vector search", "25", "In-process cache warm"],
                 ["LLM call (cloud)", "1500", "Claude-Sonnet-style provider"],
                 ["Output rails", "40", "Includes Presidio scan"],
                 ["Audit write", "5", "JSONL; 50 for WORM with fsync"],
                 ["Budget settle + metrics", "2", "-"],
                 ["Total p95 target", "< 2,000", "-"],
             ]},
        ]},
        {"type": "sub", "title": "5.2 Throughput Expectations", "body": [
            {"type": "para", "text":
                "A 2 vCPU / 2 GiB pod with STC_LLM_BULKHEAD=64 and mock "
                "LLM sustains \u223c500 QPS. With cloud LLM and "
                "p95 \u22482s, sustained QPS drops to \u223c30 per pod "
                "(bottleneck is outbound LLM concurrency). Scale "
                "horizontally; Stalwart is stateless."},
        ]},
        {"type": "sub", "title": "5.3 Cold-Start Mitigation", "body": [
            {"type": "bullets", "items": [
                "Presidio warmup at astart() removes the \u223c1s spaCy cold start.",
                "Adapter healthcheck at astart() fails the pod before traffic lands.",
                "Lazy imports for cryptography / langgraph keep cold start fast (<2s).",
            ]},
        ]},
    ]),
    Section(title="6. Multi-Region & Disaster Recovery", body=[
        {"type": "sub", "title": "6.1 Active-Passive (Recommended Default)", "body": [
            {"type": "para", "text":
                "Primary region serves all traffic. Audit log is streamed "
                "to a cross-region WORM replica (S3 Object Lock with cross-"
                "region replication). Standby region stays cold with spec "
                "image and keys but no active pods. RPO \u2248 5 minutes "
                "(audit lag); RTO \u2248 15 minutes (cold-start + DNS cutover)."},
        ]},
        {"type": "sub", "title": "6.2 Active-Active (Advanced)", "body": [
            {"type": "para", "text":
                "Stateless pods can serve traffic in any region. Cross-"
                "region shared state (audit, budget, rate-limit) requires "
                "a shared backend (distributed cache / database) "
                "conforming to the Protocol contracts. Current Tier-2 "
                "roadmap item (see STAFF_REVIEW.md)."},
        ]},
        {"type": "sub", "title": "6.3 Key Management for DR", "body": [
            {"type": "bullets", "items": [
                "STC_AUDIT_HMAC_KEY must be the same across regions to verify replicated chains.",
                "STC_TOKENIZATION_KEY must be the same for token-store replication.",
                "Spec public key (STC_SPEC_PUBLIC_KEY) must match the region that signed the spec.",
                "Use KMS replication for all three; store versioned copies so old audits remain verifiable.",
            ]},
        ]},
    ]),
    Section(title="7. Observability Stack", body=[
        {"type": "sub", "title": "7.1 Three Pillars", "body": [
            {"type": "bullets", "items": [
                "Metrics: 17 Prometheus metrics, scraped by the standard SRE stack.",
                "Traces: OpenTelemetry via STC_OTLP_ENDPOINT; every query is rooted at a stc.aquery span.",
                "Logs: structlog JSON with automatic trace-context binding; ship to Loki / Elastic / Splunk.",
            ]},
        ]},
        {"type": "sub", "title": "7.2 Audit as a Fourth Pillar", "body": [
            {"type": "para", "text":
                "Audit is NOT a log. It is the regulator-grade record of "
                "what happened. HMAC-chained, tamper-evident, "
                "per-event-class retention. Ships separately from "
                "structured logs so a SIEM retention setting cannot "
                "accidentally delete compliance evidence."},
        ]},
    ]),
    Section(title="8. Change Management", body=[
        {"type": "bullets", "items": [
            "Code change: standard PR flow; six audit test suites must pass.",
            "Spec change: resign spec with ed25519; bump version:. Audit records a system_start event with spec_version for every deploy.",
            "Prompt rotation: Trainer.publish_prompt emits prompt_registered and prompt_activated audit events. No redeploy required.",
            "Routing change: Trainer.apply_routing_optimization emits routing_updated events. Limited to models declared in spec.",
            "Secret rotation: rotate HMAC / tokenization keys quarterly. Old records remain verifiable via key_id.",
            "Emergency rollback: image-level. Pod readiness refuses to start unhealthy pods.",
        ]},
    ]),
    Section(title="9. Capacity & Cost Model", body=[
        {"type": "sub", "title": "9.1 Cost Drivers (per 1M queries)", "body": [
            {"type": "grid",
             "headers": ["Component", "Unit cost (rough)", "1M queries total"],
             "rows": [
                 ["LLM tokens (cloud)", "$0.003 / 1K tokens", "$2,000 @ 700 tokens avg"],
                 ["Embeddings (Ollama-local)", "CPU-bound", "Negligible"],
                 ["Qdrant storage", "~$0.10 / GB-month", "Depends on document corpus"],
                 ["Compute", "Varies", "~$500 for 30 QPS steady"],
                 ["Audit storage", "~$0.02 / GB", "<$50 for 1M queries"],
                 ["Tracing + metrics", "Varies", "Typically 5-10% of compute"],
             ]},
        ]},
        {"type": "sub", "title": "9.2 Per-Tenant Cost Caps", "body": [
            {"type": "bullets", "items": [
                "cost_thresholds.max_per_task_usd \u2014 per-task reservation ceiling.",
                "cost_thresholds.daily_budget_usd \u2014 rolling 24h cap.",
                "cost_thresholds.monthly_budget_usd \u2014 rolling 30d cap.",
                "maintenance_triggers.cost_above_per_task_usd \u2014 triggers degraded mode.",
                "Exceeded budgets raise STCError(reason=\"tenant_budget_exceeded\") and emit an audit record + Prometheus rejection metric.",
            ]},
        ]},
    ]),
    Section(title="10. Operational Checklists", body=[
        {"type": "sub", "title": "10.1 Pre-Deploy", "body": [
            {"type": "numbered", "items": [
                "All six test suites green; coverage \u2265 70%.",
                "pip-audit clean; SBOM generated.",
                "Spec signed; spec.yaml.sig in image.",
                "All required env vars declared (STC_AUDIT_HMAC_KEY, STC_SPEC_PUBLIC_KEY, STC_TOKENIZATION_KEY, STC_TOKEN_STORE_KEY).",
                "STC_ENV=prod on production; STC_ENV=staging on staging.",
                "terminationGracePeriodSeconds \u2265 35 on the Deployment.",
                "PodDisruptionBudget prevents simultaneous drain of too many pods.",
                "Prometheus alert rules updated; corresponding RUNBOOK.md entries exist.",
            ]},
        ]},
        {"type": "sub", "title": "10.2 Post-Deploy Verification", "body": [
            {"type": "numbered", "items": [
                "curl /readyz returns 200; every adapter reports ok.",
                "curl /metrics returns Prometheus scrape.",
                "stc-governance verify-chain on a live audit directory returns ok.",
                "Synthetic probe: run adversarial/runner.py against the new deployment; critical-severity pass rate 100%.",
                "Smoke test with a known tenant_id; verify audit record created and retrievable via DSAR.",
            ]},
        ]},
    ]),
]


def main() -> None:
    build(
        DOCS_DIR / "STC_Enterprise_Architecture.docx",
        title="Enterprise Architecture",
        subtitle="Production-grade deployment blueprint",
        tagline="HA \u00b7 Scalability \u00b7 Resilience \u00b7 Performance \u00b7 DR",
        classification="INTERNAL",
        version="Version 2.0 \u2014 April 2026",
        doc_id="STC-EA-2.0",
        toc=[
            "Purpose",
            "Deployment Topology",
            "Scaling Strategy",
            "Availability & Resilience",
            "Performance",
            "Multi-Region & Disaster Recovery",
            "Observability Stack",
            "Change Management",
            "Capacity & Cost Model",
            "Operational Checklists",
        ],
        sections=SECTIONS,
    )
    print("wrote STC_Enterprise_Architecture.docx")


if __name__ == "__main__":
    main()
