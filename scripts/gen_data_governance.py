"""Regenerate STC_Data_Governance_Framework.docx."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from docgen import Section, build, session_changes_callout  # noqa: E402

DOCS_DIR = Path("C:/Projects/stc-framework/docs")

SECTIONS: list[Section] = [
    Section(title="1. Purpose & Scope", body=[
        session_changes_callout(),
        {"type": "para", "text":
            "This document describes the STC Framework's data governance "
            "controls: data classification, PII handling, lineage, subject "
            "rights (GDPR Art. 15 and Art. 17), retention, and per-tenant "
            "isolation. It is the artifact a Chief Data Officer or DPO "
            "reviews before a regulated deployment."},
        {"type": "kv", "rows": [
            ("Regulatory scope", "GDPR (EU), CCPA / CPRA (California), HIPAA (US healthcare), FINRA 4511 / SEC 17a-4 (US financial)"),
            ("Data classes handled", "Public / Internal / Restricted (per data_sovereignty.classification)"),
            ("PII detection engine", "Microsoft Presidio + spec-declared custom patterns"),
            ("Subject-rights workflows", "DSAR (governance.dsar), Erasure (governance.erasure), Retention (governance.retention)"),
            ("Tamper evidence", "HMAC-SHA256 chain + key rotation via key_id"),
        ]},
    ]),
    Section(title="2. Data Classification", body=[
        {"type": "para", "text":
            "Every request is classified on entry. The DataClassifier "
            "combines Presidio output with custom spec-declared recognisers "
            "(regex + keyword) to assign a tier. The tier drives the "
            "routing policy \u2014 restricted data is guaranteed to reach "
            "only in-boundary models."},
        {"type": "grid",
         "headers": ["Tier", "Data types", "Permitted models", "Storage"],
         "rows": [
             ["public", "Marketing copy, product info", "cloud, VPC, local", "No special requirements"],
             ["internal", "Business logic, non-PII customer data", "VPC, local", "Encrypted at rest"],
             ["restricted", "PII, PHI, financial account numbers, MNPI", "local-only (Ollama / vLLM / Bedrock-VPC)", "AES-GCM token store + audit chain"],
         ]},
    ]),
    Section(title="3. PII Detection & Redaction", body=[
        {"type": "sub", "title": "3.1 Two-Stage Pipeline", "body": [
            {"type": "numbered", "items": [
                "Custom spec patterns first \u2014 domain-specific rules (e.g. advisor_code regex, client_portfolio keywords) win before generic detection.",
                "Presidio analyzer \u2014 language-aware entity detection for PERSON, EMAIL, PHONE, US_SSN, US_BANK_NUMBER, CREDIT_CARD, etc.",
                "Regex fallback \u2014 When Presidio unavailable, bounded-quantifier regex catches the highest-risk entities (credit card, SSN, email).",
            ]},
        ]},
        {"type": "sub", "title": "3.2 Entity Action Map", "body": [
            {"type": "grid",
             "headers": ["Entity", "Default action", "Configurable in"],
             "rows": [
                 ["CREDIT_CARD", "BLOCK (DataSovereigntyViolation)", "sentinel.pii_redaction.entities_config"],
                 ["US_SSN", "BLOCK", "spec"],
                 ["US_BANK_NUMBER", "BLOCK", "spec"],
                 ["PERSON", "MASK (replace with <PERSON>)", "spec"],
                 ["EMAIL_ADDRESS", "MASK (replace with <EMAIL>)", "spec"],
                 ["PHONE_NUMBER", "MASK", "spec"],
                 ["Custom account_number", "Classify to restricted", "data_sovereignty.classification.custom_patterns"],
             ]},
        ]},
        {"type": "sub", "title": "3.3 Where Redaction Runs", "body": [
            {"type": "bullets", "items": [
                "On every user query before the Sentinel selects a model.",
                "On every retrieved chunk before the Stalwart assembles context (indirect-PII defence).",
                "On every response in the pii_output_scan rail.",
                "Redaction counters exposed as stc_redaction_events_total{entity_type=...} for dashboarding.",
            ]},
        ]},
    ]),
    Section(title="4. Surrogate Tokenization", body=[
        {"type": "para", "text":
            "For restricted-tier data that must transit cloud models under "
            "explicit declaration, Tokenizer replaces sensitive values with "
            "HMAC-keyed reversible tokens. Tokens are resolved in-process "
            "after the response returns."},
        {"type": "kv", "rows": [
            ("Token form", "STC_TOK_<12 hex chars>"),
            ("Key source", "STC_TOKENIZATION_KEY (HMAC), STC_TOKEN_STORE_KEY (AES-GCM)"),
            ("Store permissions", "0o600 on POSIX"),
            ("Scope metadata", "Every entry carries tenant_id + created_at"),
            ("Right to erasure", "Tokenizer.erase_tenant removes all tokens for a subject"),
            ("Retention", "Tokenizer.prune_before removes tokens older than a cutoff"),
        ]},
    ]),
    Section(title="5. Data Subject Rights", body=[
        {"type": "sub", "title": "5.1 Right of Access (GDPR Art. 15 / CCPA \u00a71798.100)", "body": [
            {"type": "para", "text":
                "governance.export_tenant_records walks every tenant-scoped "
                "store and returns a single DSARRecord JSON artifact. The "
                "export itself produces an audit entry (dsar_export) so the "
                "regulator can verify the request was served within statutory "
                "windows."},
            {"type": "bullets", "items": [
                "Audit log rows filtered by tenant_id.",
                "Trainer history metadata where tenant_id is recorded.",
                "Vector store documents filtered via list_for_tenant.",
                "Prompt registrations touched by the tenant (if registry supports it).",
            ]},
        ]},
        {"type": "sub", "title": "5.2 Right to Erasure (GDPR Art. 17)", "body": [
            {"type": "para", "text":
                "governance.erase_tenant removes every tenant-scoped "
                "artifact across the system. Touches SEVEN distinct stores; "
                "a new tenant-scoped store MUST be taught about this "
                "workflow."},
            {"type": "grid",
             "headers": ["Store", "Behaviour", "Count field"],
             "rows": [
                 ["Audit (JSONL)", "Rows removed; chain recomputed", "audit_removed"],
                 ["Audit (WORM)", "Refused \u2014 ComplianceViolation. Use tokenization+key erasure for pseudonymisation.", "0"],
                 ["Trainer history", "Rows with tenant_id metadata removed", "history_removed"],
                 ["Vector store", "Documents with tenant_id metadata removed", "vector_removed"],
                 ["Token store", "Entries with tenant_id removed", "tokens_removed"],
                 ["Idempotency cache", "Cached results removed (prevents resurfacing)", "idempotency_removed"],
                 ["Budget tracker", "Rolling-bucket samples removed", "budget_samples_removed"],
                 ["Rate limiter", "Per-tenant bucket removed", "rate_limit_removed"],
             ]},
            {"type": "callout",
             "label": "WORM vs. GDPR Art. 17 tension",
             "text":
                "SEC 17a-4 requires broker-dealer records to be "
                "non-erasable. GDPR Art. 17 requires deletion on valid "
                "request. For regulated financial deployments, the "
                "compliant pattern is cryptographic pseudonymisation: "
                "tokenise PII into the audit log and erase the "
                "corresponding token-store entries on the Art. 17 "
                "request. The audit record persists; the PII does "
                "not. The contractual addendum to the DPA must "
                "disclose this.",
             "color": "FEF3C7"},
        ]},
        {"type": "sub", "title": "5.3 Erasure Audit Record", "body": [
            {"type": "para", "text":
                "erase_tenant emits an audit event with tenant_id=None "
                "(so a second erasure call does not delete the receipt) "
                "and extras carrying the count from every store. This "
                "record's retention defaults to 6 years so GDPR "
                "compliance evidence survives a naive retention override."},
        ]},
    ]),
    Section(title="6. Retention Policy", body=[
        {"type": "para", "text":
            "Retention is per-event-class, not a single knob. A naive "
            "single retention_days would delete GDPR Art. 17 evidence or "
            "audit chain seals. RetentionPolicy defaults protect the "
            "common compliance cases:"},
        {"type": "grid",
         "headers": ["Event class", "Default retention", "Rationale"],
         "rows": [
             ["default (e.g. query_completed, llm_call)", "365 days", "Operational; spec-overridable"],
             ["erasure", "6 years (2190 days)", "GDPR Art. 17 compliance evidence"],
             ["dsar_export", "6 years", "GDPR Art. 15 compliance evidence"],
             ["retention_sweep", "6 years", "SEC 17a-4 retention-as-a-process evidence"],
             ["boundary_crossing", "6 years", "Regulator traceability (who saw what where)"],
             ["data_sovereignty_violation", "6 years", "Incident evidence"],
             ["escalation_transition", "6 years", "Risk-management evidence"],
             ["audit_rotation_seal", "Forever (-1)", "Chain glue across file rotation"],
             ["retention_prune_seal", "Forever (-1)", "Chain glue across retention prune"],
         ]},
        {"type": "sub", "title": "6.1 Retention Enforcement", "body": [
            {"type": "para", "text":
                "apply_retention walks the audit backend, Trainer history, "
                "and token store. It uses the MAXIMUM cutoff across all "
                "classes for file-granularity pruning in the JSONL backend, "
                "so a file is only deleted when every class inside is "
                "expired. If any class is configured as \"forever\" (-1), "
                "pruning is refused entirely."},
        ]},
    ]),
    Section(title="7. Tenant Isolation", body=[
        {"type": "sub", "title": "7.1 Isolation Points", "body": [
            {"type": "bullets", "items": [
                "Vector search: tenant_id filter passed on every search and keyword_search call.",
                "Audit records: tenant_id stamped on every record; iter_for_tenant enables safe DSAR/erasure walks.",
                "Trainer history metadata: tenant_id copied from traces so erasure can find the row.",
                "Idempotency cache: key is (tenant_id, idempotency_key) \u2014 never plain idempotency_key.",
                "Budget: buckets keyed by tenant_id.",
                "Rate limiter: token buckets keyed by tenant_id with LRU eviction.",
                "Metrics: tenant_label() hashes high-cardinality IDs so Prometheus cardinality is bounded.",
            ]},
        ]},
        {"type": "sub", "title": "7.2 Cross-Tenant Leak Prevention", "body": [
            {"type": "para", "text":
                "A tenant-id missing from a request is treated as "
                "\"unknown\" rather than \"shared\". Vector searches "
                "without tenant_id return zero tenant-scoped results. "
                "Rate limit / budget for the \"unknown\" pseudo-tenant is "
                "a single bucket so an unauthenticated flood is bounded."},
        ]},
    ]),
    Section(title="8. Data Lineage", body=[
        {"type": "para", "text":
            "Every query produces an auditable lineage trail. A compliance "
            "officer can reconstruct \u201ca response was produced from "
            "these documents via these models at this cost\u201d from the "
            "audit alone."},
        {"type": "grid",
         "headers": ["Lineage field", "Source", "Audit event"],
         "rows": [
             ["trace_id", "system.py::aquery", "query_accepted"],
             ["data_tier", "sentinel.classifier", "llm_call"],
             ["model", "sentinel.gateway", "llm_call"],
             ["boundary_crossing", "sentinel.gateway", "llm_call"],
             ["prompt_version", "StalwartResult", "query_completed"],
             ["spec_version", "STCSpec", "query_accepted, query_completed, llm_call"],
             ["cost_usd", "StalwartResult", "query_completed"],
             ["rail_results", "Critic verdict", "query_completed, rail_failed"],
             ["redaction_entities", "sentinel.redaction", "llm_call"],
             ["citations", "stalwart._extract_citations", "query_completed"],
         ]},
    ]),
    Section(title="9. Data Minimisation", body=[
        {"type": "para", "text":
            "Multiple controls enforce GDPR Art. 5(1)(c) (\"data collected "
            "shall be adequate, relevant, and limited to what is "
            "necessary\")."},
        {"type": "bullets", "items": [
            "record_from_trace filters query / response / context / chunks / citations out of Trainer history metadata. Only aggregates (accuracy, cost, latency) plus tenant_id reach the history store.",
            "notifications._strip_pii scrubs query / response / context / tenant_id / email / user_id / prompt / messages / metadata before any Slack or third-party webhook send.",
            "Stalwart exception suppression stores only exception class name on StalwartResult.error, never message content.",
            "Default STC_LOG_CONTENT=false drops content fields from structured logs at INFO and above.",
            "Chunk-level size caps (max_chunk_chars, max_chunks) cap how much document text reaches the LLM even when the retrieval is oversized.",
        ]},
    ]),
    Section(title="10. Regulatory Crosswalk", body=[
        {"type": "grid",
         "headers": ["Regulation", "Provision", "Implementation"],
         "rows": [
             ["GDPR", "Art. 5(1)(c) data minimisation", "record_from_trace + _strip_pii + chunk caps"],
             ["GDPR", "Art. 5(1)(e) storage limitation", "apply_retention per-event-class"],
             ["GDPR", "Art. 15 right of access", "governance.export_tenant_records + stc-governance dsar"],
             ["GDPR", "Art. 17 right to erasure", "governance.erase_tenant + stc-governance erase"],
             ["GDPR", "Art. 25 privacy by default", "Presidio redaction pre-LLM + chunk redaction"],
             ["GDPR", "Art. 30 records of processing", "26-event AuditEvent catalogue + HMAC chain"],
             ["GDPR", "Art. 32 security of processing", "See Security Architecture doc"],
             ["CCPA / CPRA", "\u00a71798.100 right to know", "DSAR export"],
             ["CCPA / CPRA", "\u00a71798.105 right to delete", "Erasure workflow"],
             ["HIPAA", "\u00a7164.312(b) audit controls", "HMAC-chained append-only log"],
             ["HIPAA", "\u00a7164.312(c) integrity", "verify_chain"],
             ["HIPAA", "\u00a7164.312(e) transmission security", "data-sovereignty 3-layer routing + TLS enforced at gateway"],
             ["SEC", "17a-4(f) electronic records WORM", "WORMAuditBackend"],
             ["FINRA", "4511 retention 6 years", "RetentionPolicy defaults"],
             ["SOX", "\u00a7404 change control", "Signed spec + audit of prompt / routing changes"],
         ]},
    ]),
]


def main() -> None:
    build(
        DOCS_DIR / "STC_Data_Governance_Framework.docx",
        title="Data Governance Framework",
        subtitle="Classification \u00b7 Redaction \u00b7 Subject Rights \u00b7 Retention",
        tagline="GDPR \u00b7 CCPA \u00b7 HIPAA \u00b7 SEC 17a-4 \u00b7 FINRA 4511",
        classification="INTERNAL",
        version="Version 2.0 \u2014 April 2026",
        doc_id="STC-DG-2.0",
        toc=[
            "Purpose & Scope",
            "Data Classification",
            "PII Detection & Redaction",
            "Surrogate Tokenization",
            "Data Subject Rights",
            "Retention Policy",
            "Tenant Isolation",
            "Data Lineage",
            "Data Minimisation",
            "Regulatory Crosswalk",
        ],
        sections=SECTIONS,
    )
    print("wrote STC_Data_Governance_Framework.docx")


if __name__ == "__main__":
    main()
