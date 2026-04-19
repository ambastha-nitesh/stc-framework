"""Regenerate STC_Security_Architecture.docx."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from docgen import Section, build, session_changes_callout  # noqa: E402

DOCS_DIR = Path("C:/Projects/stc-framework/docs")

SECTIONS: list[Section] = [
    Section(title="1. Executive Summary", body=[
        session_changes_callout(),
        {"type": "para", "text":
            "This document captures the STC Framework's security architecture. "
            "It is the artifact a CISO, security architect, or external "
            "assessor reviews to confirm that the framework's claims about "
            "data sovereignty, tamper evidence, and defence in depth are "
            "backed by code, tests, and runtime enforcement. Every control "
            "listed has a corresponding regression test in the six audit "
            "suites under tests/unit/."},
        {"type": "sub", "title": "1.1 Security Posture at a Glance", "body": [
            {"type": "grid",
             "headers": ["Property", "Mechanism", "Evidence"],
             "rows": [
                 ["Tamper-evident audit", "HMAC-SHA256 chain per record", "observability/audit.py::verify_chain"],
                 ["WORM compliance", "WORMAuditBackend refuses erase/prune", "adapters/audit_backend/worm.py"],
                 ["Signed compliance posture", "Ed25519 spec signature at startup", "spec/signing.py"],
                 ["Fail-closed in prod", "Six astart() invariants", "system.py::_enforce_startup_invariants"],
                 ["Restricted data stays local", "3-layer routing enforcement", "spec/models.py + sentinel/gateway.py"],
                 ["Data-tier PII redaction", "Presidio + custom recognisers", "sentinel/redaction.py"],
                 ["Indirect-PII defence", "Retrieved chunks redacted pre-LLM", "stalwart/agent.py::_retrieve"],
                 ["Prompt-injection defence", "16 rule families; pre + post rails", "critic/validators/injection.py + security/injection.py"],
                 ["Tenant isolation", "tenant_id filter on every vector search", "adapters/vector_store/*"],
                 ["Supply-chain integrity", "pip-audit + SBOM + secret scan in CI", ".github/workflows/ci.yml"],
             ]},
        ]},
    ]),
    Section(title="2. Threat Model", body=[
        {"type": "sub", "title": "2.1 Actors and Attack Surfaces", "body": [
            {"type": "grid",
             "headers": ["Actor", "Capabilities", "Primary target"],
             "rows": [
                 ["External client", "HTTPS POST to /v1/query", "Prompt injection, DoS, PII exfiltration, budget exhaustion"],
                 ["Internal operator (low priv)", "Read logs / metrics", "PII leakage via logs, lateral movement"],
                 ["Internal operator (root)", "Filesystem + service config", "Audit tampering, spec replacement, key extraction"],
                 ["Compromised Trainer", "Mutate routing / prompts", "Data exfiltration via cloud provider redirection"],
                 ["Poisoned document", "Arbitrary bytes in vector store", "Indirect prompt injection, PII planting"],
                 ["LLM provider insider", "Log queries post-redaction", "Aggregated re-identification (limited by redaction)"],
                 ["Network adversary", "Observe / MITM transit", "Side-channel (TLS handles confidentiality)"],
             ]},
        ]},
        {"type": "sub", "title": "2.2 Attack Tree (condensed, MITRE ATLAS-aligned)", "body": [
            {"type": "bullets", "items": [
                "AML.T0051 Prompt injection \u2192 blocked by input rails (16 rule families) + output_injection_scan.",
                "AML.T0054 Jailbreak / roleplay \u2192 role_switch rule + scope_check.",
                "AML.T0024 Sensitive info exfiltration \u2192 exfiltrate_system_prompt rule + pii_output_scan + data-tier routing.",
                "AML.T0043 Hallucination induction \u2192 numerical_accuracy + hallucination_detection + citation_required.",
                "ReDoS via crafted input \u2192 bounded-quantifier regex + input size caps.",
                "Audit tampering \u2192 HMAC-SHA256 chain + WORM backend + OS-level immutability.",
                "Spec replacement \u2192 ed25519 signature verification at startup.",
                "Cross-tenant leak \u2192 tenant_id filter on vector / audit / history / budget / idempotency.",
                "Budget-exhaustion / cost DDoS \u2192 per-tenant rolling-bucket budget + rate limiter + bulkhead.",
            ]},
        ]},
    ]),
    Section(title="3. Defence in Depth", body=[
        {"type": "grid",
         "headers": ["Layer", "Location", "What it catches"],
         "rows": [
             ["L1 Input size / Unicode", "system.py + security/limits.py + security/sanitize.py", "Oversize payloads, zero-width smuggling"],
             ["L2 Header sanitisation", "security/sanitize.py::sanitize_header_value", "CR/LF injection into audit logs"],
             ["L3 Rate limit + budget", "governance/rate_limit.py + budget.py", "Cost exhaustion, tenant flooding"],
             ["L4 Input rails (Critic)", "critic/validators/injection.py", "16 injection rule families"],
             ["L5 Data-tier classification", "sentinel/classifier.py", "Tier mis-routing"],
             ["L6 PII redaction", "sentinel/redaction.py", "PII in user query or chunks"],
             ["L7 Routing policy", "sentinel/gateway.py + spec/models.py", "Restricted data reaching external LLM"],
             ["L8 Output rails (Critic)", "critic/validators/*.py", "Hallucination, missing citation, output injection"],
             ["L9 Audit chain", "observability/audit.py + WORMAuditBackend", "Evidence tampering"],
             ["L10 Escalation", "resilience/degradation.py + critic/escalation.py", "Progressive risk mitigation"],
         ]},
    ]),
    Section(title="4. Cryptographic Controls", body=[
        {"type": "sub", "title": "4.1 Audit HMAC", "body": [
            {"type": "kv", "rows": [
                ("Algorithm", "HMAC-SHA256"),
                ("Key length", "\u2265 16 bytes (32 bytes recommended), base64-urlsafe"),
                ("Key source", "STC_AUDIT_HMAC_KEY environment variable"),
                ("Key rotation", "key_id stamped per record; rotation preserves verifiability"),
                ("Prod fallback", "Refuses to boot without STC_AUDIT_HMAC_KEY"),
                ("Dev fallback", "Per-process ephemeral key; warning logged"),
                ("Verification", "observability.audit.verify_chain"),
                ("Verification mode", "strict (from genesis) or accept_unknown_genesis (post-prune)"),
            ]},
        ]},
        {"type": "sub", "title": "4.2 Spec Signature", "body": [
            {"type": "kv", "rows": [
                ("Algorithm", "Ed25519 (EdDSA, Curve25519)"),
                ("Signature format", "Raw 64-byte signature in spec.yaml.sig sidecar"),
                ("Public key", "32-byte raw, base64-urlsafe, in STC_SPEC_PUBLIC_KEY"),
                ("Signed content", "SHA-256 digest of the spec file contents"),
                ("Prod enforcement", "Missing signature / missing key / invalid signature all raise"),
                ("Recommended signer", "Hardware token (Yubikey) / sigstore / HSM"),
            ]},
        ]},
        {"type": "sub", "title": "4.3 Token Store", "body": [
            {"type": "kv", "rows": [
                ("Scheme", "HMAC-SHA256 surrogate tokens + AES-256-GCM file store"),
                ("Token form", "STC_TOK_<12 hex chars>"),
                ("HMAC key", "STC_TOKENIZATION_KEY"),
                ("Store key", "STC_TOKEN_STORE_KEY (32-byte base64-urlsafe)"),
                ("File permissions", "0o600 on POSIX, atomic O_NOFOLLOW write"),
                ("Metadata per entry", "tenant_id, created_at (enables erasure + retention)"),
                ("Prod strictness", "STC_TOKENIZATION_STRICT=1 required"),
            ]},
        ]},
    ]),
    Section(title="5. Input Validation & Sanitisation", body=[
        {"type": "grid",
         "headers": ["Control", "Value", "Where enforced"],
         "rows": [
             ["max_query_chars", "8,000", "security/limits.py"],
             ["max_response_chars", "40,000", "security/limits.py"],
             ["max_context_chars", "120,000", "security/limits.py"],
             ["max_chunk_chars", "8,000", "security/limits.py"],
             ["max_chunks", "50", "security/limits.py"],
             ["max_header_value_chars", "256", "security/limits.py"],
             ["max_request_bytes (Flask)", "64 KiB", "service/app.py MAX_CONTENT_LENGTH"],
             ["Zero-width / BiDi override stripping", "Pre-rail", "security/sanitize.py::strip_zero_width"],
             ["Header CR/LF/NUL stripping", "Entry + Flask", "security/sanitize.py::sanitize_header_value"],
             ["Chunk chat-role markup sanitisation", "Stalwart retrieve", "security/sanitize.py::sanitize_context_chunk"],
         ]},
    ]),
    Section(title="6. Prompt Injection Rules", body=[
        {"type": "para", "text":
            "Sixteen rule families across nine categories, applied after "
            "zero-width normalisation so homoglyph smuggling is caught."},
        {"type": "bullets", "items": [
            "override.en / override.en.targeted \u2014 'ignore / disregard / forget / bypass ... previous / system instructions'.",
            "override.de / override.es / override.fr / override.it \u2014 multilingual equivalents.",
            "system_override \u2014 bracket tags [SYSTEM OVERRIDE], [ADMIN], [ROOT], [JAILBREAK].",
            "developer_mode \u2014 developer / admin / DAN mode requests.",
            "disable_guardrails \u2014 disable / turn off / deactivate guardrails / safety.",
            "role_switch \u2014 'you are now' / 'pretend to be' / 'act as'.",
            "exfiltrate_system_prompt \u2014 reveal / show / print / output system prompt.",
            "translate_exfiltration \u2014 translate system prompt / instructions.",
            "chat_markup \u2014 </s>, [INST], <|im_start|>, <|system|>.",
            "role_prefix_spoof \u2014 'user: ignore...', 'system: you are now...'.",
            "delimiter_breakout \u2014 ``` end system, <!-- end instructions -->.",
            "url_exfiltration \u2014 URL query params containing 'prompt=' / 'system='.",
            "encoded_payload \u2014 base64 run that decodes to known injection verbs.",
        ]},
    ]),
    Section(title="7. Secure Development Lifecycle", body=[
        {"type": "sub", "title": "7.1 CI Pipeline", "body": [
            {"type": "bullets", "items": [
                "ruff + black + mypy \u2014 every PR.",
                "pytest across Python 3.10, 3.11, 3.12 with coverage gate \u2265 70%.",
                "pip-audit --strict \u2014 CVE scan on every CI run.",
                "CycloneDX SBOM artifact on every CI run.",
                "Regex-based secret scan blocks AWS / OpenAI / Slack tokens + private keys from being committed.",
                "Six audit suites (security, privacy, observability, enterprise, staff_review, staff_review_round2) must pass before release.",
            ]},
        ]},
        {"type": "sub", "title": "7.2 Adversarial Testing", "body": [
            {"type": "para", "text":
                "src/stc_framework/adversarial/probes.py contains a MITRE "
                "ATLAS-aligned probe catalog. The runner submits each probe "
                "via STCSystem.aquery and reports pass/fail. AIUC-1 "
                "B_adversarial_robustness control requires \u2265 90% pass; "
                "F001 requires 100% critical-severity pass."},
        ]},
    ]),
    Section(title="8. Secret Management", body=[
        {"type": "grid",
         "headers": ["Secret", "Purpose", "Recommended source"],
         "rows": [
             ["STC_AUDIT_HMAC_KEY", "Audit chain seal", "KMS / HSM; rotate quarterly via key_id stamping"],
             ["STC_SPEC_PUBLIC_KEY", "Spec signature verification", "Pinned in deploy image; private key on Yubikey"],
             ["STC_TOKENIZATION_KEY", "Surrogate token HMAC", "KMS; same per deployment"],
             ["STC_TOKEN_STORE_KEY", "AES-GCM token store", "KMS envelope encryption"],
             ["LITELLM_MASTER_KEY", "LLM gateway", "Secrets Manager"],
             ["Provider API keys", "OpenAI / Anthropic / Bedrock", "Secrets Manager + IAM roles"],
             ["SLACK_WEBHOOK_URL", "Notifier", "Secrets Manager"],
         ]},
        {"type": "callout",
         "label": "Secret hygiene checklist",
         "text":
            "1) No secret in git \u2014 enforced by CI secret scan. 2) No "
            "secret in logs \u2014 PII filter drops content fields by default. "
            "3) No secret in error messages \u2014 Stalwart suppresses "
            "exception args. 4) No secret in metric labels \u2014 tenant_label "
            "hashes high-cardinality IDs. 5) Rotate every 90 days; audit "
            "chain remains verifiable across rotations.",
         "color": "FEE2E2"},
    ]),
    Section(title="9. Incident Response", body=[
        {"type": "sub", "title": "9.1 Suspected Audit Tampering", "body": [
            {"type": "numbered", "items": [
                "Stop writes \u2014 scale deployment to 0.",
                "Snapshot the entire audit directory (keep .worm-marker if present).",
                "Run stc-governance verify-chain in strict mode; note the first failing record.",
                "Diff against any replica (S3 Object Lock, Immudb).",
                "Rotate STC_AUDIT_HMAC_KEY; old records remain verifiable under their key_id.",
                "File the disclosure per SOX 404, NYDFS Part 500 \u00a7500.17, or the tenant DPA (within 72 hours typical).",
            ]},
        ]},
        {"type": "sub", "title": "9.2 Suspected Data Exfiltration", "body": [
            {"type": "numbered", "items": [
                "Set DegradationState=PAUSED manually; /readyz returns 503.",
                "Pull all boundary_crossing audit records for the suspected window.",
                "Check stc_cost_usd_total by tenant for anomalies.",
                "Check stc_boundary_crossings_total for spike in restricted\u2192non-local.",
                "Engage forensics; preserve audit records under legal hold.",
            ]},
        ]},
        {"type": "sub", "title": "9.3 Suspected Spec Tampering", "body": [
            {"type": "para", "text":
                "If spec signature verification fails at startup, the process "
                "refuses to boot. If you suspect runtime tampering (spec was "
                "valid at startup but runtime behaviour is anomalous): "
                "restart the pod (signature is re-verified). If it starts "
                "cleanly, the running spec differs from disk \u2014 check for "
                "file-system tampering. If startup now fails, you have the "
                "evidence: hash of tampered spec vs. signed spec."},
        ]},
    ]),
    Section(title="10. Compliance Mapping", body=[
        {"type": "grid",
         "headers": ["Framework", "Control area", "Implementation"],
         "rows": [
             ["ISO 27001 A.12.4", "Logging and monitoring", "HMAC-chained audit, 17 Prometheus metrics, OTel traces"],
             ["NIST 800-53 AU-10", "Non-repudiation", "HMAC chain + ed25519 spec signatures"],
             ["NIST 800-53 SI-10", "Information input validation", "security/limits.py + security/sanitize.py"],
             ["NIST 800-53 SC-28", "Protection at rest", "AES-GCM token store + HMAC chain + envelope encryption recommended"],
             ["NIST 800-53 IR-4", "Incident handling", "RUNBOOK.md + stc-governance CLI"],
             ["SEC 17a-4(f)", "Electronic records WORM", "WORMAuditBackend"],
             ["FINRA 4511", "Record retention 6 years", "RetentionPolicy defaults"],
             ["GDPR Art. 32", "Security of processing", "All of above + 3-layer data sovereignty"],
             ["SOC 2 CC6.1", "Logical access", "VirtualKeyManager per-persona keys"],
             ["SOC 2 CC7.2", "System monitoring", "Prometheus + audit events"],
             ["AIUC-1 B", "Adversarial robustness", "test_security.py + adversarial probe suite"],
         ]},
    ]),
]


def main() -> None:
    build(
        DOCS_DIR / "STC_Security_Architecture.docx",
        title="Security Architecture",
        subtitle="Threat Model \u00b7 Controls \u00b7 Incident Response",
        tagline="For regulated enterprise deployments (SEC / FINRA / HIPAA / GDPR)",
        classification="INTERNAL",
        version="Version 2.0 \u2014 April 2026",
        doc_id="STC-SEC-2.0",
        toc=[
            "Executive Summary",
            "Threat Model",
            "Defence in Depth",
            "Cryptographic Controls",
            "Input Validation & Sanitisation",
            "Prompt Injection Rules",
            "Secure Development Lifecycle",
            "Secret Management",
            "Incident Response",
            "Compliance Mapping",
        ],
        sections=SECTIONS,
    )
    print("wrote STC_Security_Architecture.docx")


if __name__ == "__main__":
    main()
