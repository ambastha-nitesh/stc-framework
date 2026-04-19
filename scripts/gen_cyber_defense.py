"""Regenerate STC_Cyber_Defense_Framework.docx."""

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
            "This document describes the STC Framework's cyber-defence "
            "posture: offensive testing, runtime firewall, network "
            "hardening, container security, supply-chain controls, and "
            "response playbooks. Paired with the Security Architecture "
            "document (which covers cryptographic and governance "
            "controls), this is the artifact a Red Team or SOC lead "
            "reviews."},
    ]),
    Section(title="2. Adversarial Testing", body=[
        {"type": "sub", "title": "2.1 MITRE ATLAS Probe Catalog", "body": [
            {"type": "para", "text":
                "src/stc_framework/adversarial/probes.py contains the "
                "baseline probe set. The runner submits each probe via "
                "STCSystem.aquery and scores pass/fail against the "
                "expected behaviour (blocked, refused, or safe_response)."},
            {"type": "grid",
             "headers": ["Probe ID", "ATLAS technique", "Category", "Expected"],
             "rows": [
                 ["adv-001", "AML.T0051", "prompt_injection", "blocked"],
                 ["adv-002", "AML.T0024", "data_exfiltration", "refused"],
                 ["adv-003", "AML.T0043", "hallucination_induction", "safe_response"],
                 ["adv-004", "AML.T0051", "prompt_injection", "blocked"],
                 ["adv-005", "AML.T0024", "data_exfiltration", "blocked"],
                 ["adv-006", "AML.T0054", "jailbreak", "blocked"],
                 ["adv-007", "AML.T0043", "hallucination_induction", "safe_response"],
                 ["adv-008", "AML.T0051", "prompt_injection", "blocked"],
             ]},
        ]},
        {"type": "sub", "title": "2.2 AIUC-1 Pass Criteria", "body": [
            {"type": "bullets", "items": [
                "B_adversarial_robustness: overall pass rate \u2265 90%.",
                "F001_prevent_misuse: critical-severity probes 100% pass.",
                "Run quarterly at minimum; add to CI nightly at recommended cadence.",
            ]},
        ]},
        {"type": "sub", "title": "2.3 Injection Rule Coverage", "body": [
            {"type": "para", "text":
                "security.injection.INJECTION_RULES covers 16 families "
                "across 9 attack categories. Full list in the Security "
                "Architecture document \u00a76; summary below."},
            {"type": "bullets", "items": [
                "English override (2 variants), multilingual override (DE/ES/FR/IT).",
                "Bracket-tag overrides (SYSTEM OVERRIDE, ADMIN, ROOT, JAILBREAK).",
                "Developer / DAN / god-mode requests.",
                "Role switching (you-are-now, pretend-to-be, act-as).",
                "Exfiltration (reveal / show / output system prompt).",
                "Translation-based exfiltration.",
                "Chat markup smuggling (</s>, [INST], <|im_start|>).",
                "Role-prefix spoofing (user:, system:, assistant:).",
                "Delimiter breakout (``` end system, <!-- end instructions -->).",
                "URL query exfiltration.",
                "Base64-encoded payload detection (decodes to known verbs).",
            ]},
        ]},
    ]),
    Section(title="3. Runtime Protection", body=[
        {"type": "sub", "title": "3.1 Input Rails (pre-LLM)", "body": [
            {"type": "bullets", "items": [
                "Size caps (security/limits.py) reject oversized queries before any CPU is spent.",
                "Unicode normalisation (strip_zero_width) eliminates homoglyph smuggling.",
                "Header sanitisation (sanitize_header_value) prevents log injection.",
                "Prompt-injection rail fires before any LLM call \u2014 no tokens spent on blocked requests.",
                "Per-tenant rate limiter (token bucket with LRU) + per-tenant budget (rolling day buckets) prevent cost-exhaustion DDoS.",
            ]},
        ]},
        {"type": "sub", "title": "3.2 Output Rails (post-LLM)", "body": [
            {"type": "bullets", "items": [
                "Numerical accuracy, hallucination detection, scope check, PII output scan.",
                "Citation required \u2014 numerical claims must carry [Source:].",
                "Toxicity check.",
                "Output-injection scan \u2014 reflective attacks that make the model echo instructions to a downstream agent are caught at our boundary.",
            ]},
        ]},
        {"type": "sub", "title": "3.3 Resilience Primitives", "body": [
            {"type": "grid",
             "headers": ["Primitive", "Scope", "Impl"],
             "rows": [
                 ["Retry with full-jitter exponential backoff", "LLM / vector / embedding / guardrail", "tenacity-based in resilience/retry.py"],
                 ["Per-downstream circuit breaker", "LLM / vector / embedding", "resilience/circuit.py (native async)"],
                 ["asyncio timeout", "All I/O", "resilience/timeout.py (3.10/3.11 compatible)"],
                 ["Bulkhead (asyncio Semaphore)", "LLM / vector / embedding / guardrails", "resilience/bulkhead.py"],
                 ["Fallback chain", "LLM routing per tier", "resilience/fallback.py"],
                 ["Global degradation state machine", "NORMAL \u2192 DEGRADED \u2192 QUARANTINE \u2192 PAUSED", "resilience/degradation.py"],
             ]},
        ]},
    ]),
    Section(title="4. Network Hardening", body=[
        {"type": "bullets", "items": [
            "Flask service binds with security headers (X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Referrer-Policy: no-referrer, Cache-Control: no-store, HSTS).",
            "MAX_CONTENT_LENGTH bounds request body at 64 KiB by default.",
            "Werkzeug HTTPException handler preserves correct status codes (413, 404, 405 etc.) instead of masking as 500.",
            "Generic error handler never leaks internal class names or stack traces to clients.",
            "Optional flask-limiter for per-tenant request rate limiting at the HTTP layer, in addition to the library-level TenantRateLimiter.",
            "SIGTERM handler calls runner.shutdown(drain_timeout=30) so K8s preStop hooks drain in-flight traffic cleanly.",
        ]},
    ]),
    Section(title="5. Container & Runtime Hardening", body=[
        {"type": "grid",
         "headers": ["Control", "Recommendation"],
         "rows": [
             ["Base image", "distroless-python or minimal Alpine; no shell"],
             ["User", "Non-root UID/GID"],
             ["Filesystem", "Read-only root FS; writable volume only for audit directory"],
             ["Audit volume mount", "SELinux/AppArmor profile limits writes to append-only"],
             ["Linux capabilities", "Drop CAP_LINUX_IMMUTABLE on WORM-audit volumes; apply chattr +a"],
             ["Network egress", "Restrict to declared LLM / vector / observability endpoints only"],
             ["Secret delivery", "Mounted secrets, not env vars in deploy manifest; rotate every 90 days"],
             ["Resource limits", "CPU + memory requested and limited; OOM-killer cannot truncate audit"],
             ["Termination grace", "terminationGracePeriodSeconds \u2265 35s (\u2265 drain_timeout + 5s)"],
         ]},
    ]),
    Section(title="6. Supply Chain Security", body=[
        {"type": "sub", "title": "6.1 CI Controls", "body": [
            {"type": "bullets", "items": [
                "pip-audit --strict runs on every CI push \u2014 fails on known CVE in the dependency tree.",
                "CycloneDX SBOM artifact generated on every run; retained per release.",
                "Secret scan: regex blocks AWS keys (AKIA...), Slack tokens (xoxb...), private keys (-----BEGIN ... PRIVATE KEY-----), OpenAI keys (sk-...).",
                "Python matrix: 3.10, 3.11, 3.12.",
                "ruff + black + mypy strict mode.",
                "Coverage gate \u2265 70%; current 81.6%.",
            ]},
        ]},
        {"type": "sub", "title": "6.2 Release Controls", "body": [
            {"type": "bullets", "items": [
                "All six audit test suites must pass before release.",
                "Version in pyproject.toml matches git tag.",
                "SBOM attached to GitHub release.",
                "cosign / sigstore signing of the release artifact recommended (not auto-enabled).",
            ]},
        ]},
        {"type": "sub", "title": "6.3 Dependency Boundaries", "body": [
            {"type": "bullets", "items": [
                "Core runtime deps are minimal: pydantic, structlog, tenacity, httpx, opentelemetry, numpy, cryptography.",
                "Adapter deps are optional: [litellm], [qdrant], [langfuse], [nemo], [guardrails-ai], [lightning], [parquet].",
                "New top-level dep requires review + pip-audit pass + SBOM regen.",
            ]},
        ]},
    ]),
    Section(title="7. Detection & Monitoring", body=[
        {"type": "sub", "title": "7.1 Signal Surfaces", "body": [
            {"type": "grid",
             "headers": ["Surface", "Content", "Pivot"],
             "rows": [
                 ["Prometheus", "17 metrics including cost, tokens, circuit state, escalation level", "trace_id-labelled exemplars"],
                 ["OpenTelemetry", "Span tree for every query rooted at stc.aquery", "Spans carry trace_id + request_id + tenant_id + spec_version"],
                 ["structlog JSON", "Every log line carries trace_id, span_id, tenant_id, persona, request_id", "Elastic / Splunk / Loki-friendly"],
                 ["Audit log", "HMAC-chained record per meaningful event", "Regulator-grade; not a log replacement"],
             ]},
        ]},
        {"type": "sub", "title": "7.2 Detection Rules (suggested)", "body": [
            {"type": "bullets", "items": [
                "Alert on stc_circuit_breaker_state{downstream=*} == 2 for \u2265 1 min (upstream outage).",
                "Alert on stc_escalation_level \u2265 3 (Critic paused).",
                "Alert on stc_queries_total{action=\"block_input\"} / total > 5% (injection storm).",
                "Alert on stc_tenant_budget_rejections_total > 0 per tenant (cost runaway).",
                "Alert on audit-volume drop: sudden decrease in stc_governance_events_total (broken audit pipeline).",
                "Alert on verify-chain failure (security incident \u2014 page immediately).",
                "Alert on spec_version gauge change when no deploy happened (spec tampering).",
            ]},
        ]},
    ]),
    Section(title="8. Incident Response Playbooks", body=[
        {"type": "sub", "title": "8.1 Prompt Injection Storm", "body": [
            {"type": "numbered", "items": [
                "Identify the tenant via stc_queries_total{action=\"block_input\", tenant=...}.",
                "Pull the last 100 rail_failed audit records for that tenant.",
                "Check for pattern: all one rule category \u2192 likely crawler; diverse \u2192 likely red team.",
                "If malicious: tighten the tenant's rate limit or temporarily revoke their virtual key.",
                "Open a follow-up ticket to add any novel patterns to the rule set.",
            ]},
        ]},
        {"type": "sub", "title": "8.2 Suspected Exfiltration via Cloud LLM", "body": [
            {"type": "numbered", "items": [
                "Manually set DegradationState to PAUSED \u2014 every new request returns 503.",
                "Pull all boundary_crossing audit records for the window.",
                "Check stc_cost_usd_total{model=cloud-provider, tenant=...} for anomaly.",
                "Check the redacted-entities list per-record \u2014 was a BLOCK entity slipped through?",
                "If confirmed: rotate STC_AUDIT_HMAC_KEY, engage forensics, notify DPO, file disclosure per DPA.",
            ]},
        ]},
        {"type": "sub", "title": "8.3 Audit Chain Break", "body": [
            {"type": "numbered", "items": [
                "Stop writes (scale deployment to 0).",
                "Snapshot audit directory.",
                "Run stc-governance verify-chain in strict mode; note first failing entry.",
                "If failure is immediately after a retention sweep: expected. Re-run with accept_unknown_genesis=True to confirm.",
                "If failure is in the middle of an unpruned run: tampering. Treat as P0 security incident.",
            ]},
        ]},
    ]),
    Section(title="9. Red Team & Bug Bounty", body=[
        {"type": "bullets", "items": [
            "Quarterly external red team recommended \u2014 scope: Flask service, audit chain, data sovereignty, spec signing.",
            "Internal red team: run adversarial/runner.py with expanded probe set before each release.",
            "Bug bounty program scope (recommended): any bypass of prompt-injection, PII, data sovereignty, or audit integrity is in scope. MNPI detection (customer-configurable) out of scope unless bypass is in core rule engine.",
        ]},
    ]),
    Section(title="10. Compliance Mapping", body=[
        {"type": "grid",
         "headers": ["Framework", "Area", "Evidence"],
         "rows": [
             ["NIST 800-53 RA-5", "Vulnerability scanning", "pip-audit in CI"],
             ["NIST 800-53 SR-11", "Component authenticity", "CycloneDX SBOM + cosign (recommended)"],
             ["NIST 800-53 SI-3", "Malicious code protection", "pip-audit + secret scan + signed spec"],
             ["NIST 800-53 SI-4", "Monitoring", "Prometheus + OTel + audit chain"],
             ["ISO 27001 A.12.6", "Technical vulnerability management", "pip-audit + CycloneDX"],
             ["ISO 27001 A.14.2.8", "System security testing", "Adversarial probe suite + 6 audit test suites"],
             ["SOC 2 CC7.2", "System monitoring", "Prometheus metrics + alert rules"],
             ["SOC 2 CC7.3", "Change evaluation / threat mitigation", "Ed25519 spec signing + chain integrity"],
         ]},
    ]),
]


def main() -> None:
    build(
        DOCS_DIR / "STC_Cyber_Defense_Framework.docx",
        title="Cyber Defense Framework",
        subtitle="Offensive Testing \u00b7 Runtime Firewall \u00b7 Detection \u00b7 Response",
        tagline="Supply-chain integrity + adversarial testing + incident playbooks",
        classification="INTERNAL",
        version="Version 2.0 \u2014 April 2026",
        doc_id="STC-CYBER-2.0",
        toc=[
            "Purpose",
            "Adversarial Testing",
            "Runtime Protection",
            "Network Hardening",
            "Container & Runtime Hardening",
            "Supply Chain Security",
            "Detection & Monitoring",
            "Incident Response Playbooks",
            "Red Team & Bug Bounty",
            "Compliance Mapping",
        ],
        sections=SECTIONS,
    )
    print("wrote STC_Cyber_Defense_Framework.docx")


if __name__ == "__main__":
    main()
