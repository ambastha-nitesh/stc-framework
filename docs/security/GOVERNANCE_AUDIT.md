# STC Framework — Data Privacy & Governance Audit

This document records the data-privacy and regulatory-governance review
performed on the STC Framework and the controls added in response.

Scope covers GDPR, CCPA/CPRA, HIPAA (to the extent a framework can), SOC 2
(CC7 logging, CC8 change, CC9 governance), and the AIUC-1 controls the
reference spec maps to.

Testing posture: `pytest tests/unit/test_privacy.py -v` must be green on
every commit. Every regression test corresponds to a finding below.

---

## P1 — Incomplete audit coverage

**Severity:** High.

**Finding.** Only LLM calls produced an audit record. Query acceptance,
input-rail rejection, every individual rail failure, feedback
submission, routing reorders, prompt rotations, retention sweeps,
DSAR exports, and erasure calls all went unlogged. That leaves gaps
where an operator cannot reconstruct what happened for a given
`trace_id` — a problem for SOC 2 CC7, GDPR Art. 30 (records of
processing activities), and the AIUC-1 `E_audit_trail` control.

**Mitigation.**
- New `stc_framework.governance.events.AuditEvent` enum catalogues
  every auditable action (22 event types).
- `STCSystem.aquery` emits `query_accepted`, `query_rejected`,
  `rail_failed` (per rail), `query_completed`, plus the existing
  `llm_call` and `boundary_crossing`.
- `STCSystem.submit_feedback` emits `feedback_submitted`.
- `RoutingController.apply` emits `routing_updated`.
- `PromptController.publish` emits `prompt_registered` and
  `prompt_activated`.
- `apply_retention` emits `retention_sweep`.
- `erase_tenant` emits `erasure`.
- `export_tenant_records` emits `dsar_export`.

**Regression tests:** `TestAuditCoverage`.

---

## P2 — Audit log was not tamper-evident

**Severity:** Critical. Audit records were appended as plain JSONL.
Any local-file-level attacker could edit a line, delete a line, or
re-order history with no way to detect it.

**Mitigation.**
- `AuditRecord` gains `prev_hash` and `entry_hash` fields.
- Every `JSONLAuditBackend.append` call computes
  `entry_hash = SHA-256(record_with_prev_hash)` and chains it to the
  previous record's `entry_hash`. The very first record chains to
  ``0 * 64``.
- `stc_framework.observability.audit.verify_chain(records)` walks a
  sequence and reports the first break. Operators can run this
  programmatically or as part of a SOC 2 control test.
- Erasure re-computes the chain after removing rows so the remaining
  records are still verifiable (otherwise `erase_tenant` would leave
  the log in a broken state).

**Regression tests:** `TestAuditTamperEvidence`.

---

## P3 — Retention was declared but never enforced

**Severity:** High. `audit.retention_days` lived in the spec but no
code ever deleted old records — a direct conflict with GDPR Art. 5(1)(e)
(storage limitation) and with the customer-facing retention promise
in `spec-examples/financial_qa.yaml`.

**Mitigation.**
- `stc_framework.governance.apply_retention(system)` sweeps:
  - audit backend (`prune_before(cutoff_iso)`),
  - trainer history store (`prune_before(cutoff)`),
  - surrogate token store (`prune_before(cutoff)`).
- `JSONLAuditBackend.prune_before` deletes at file granularity so the
  hash chain of remaining records stays valid; finer-grained pruning
  requires a DB-backed backend.
- The sweep itself emits a `retention_sweep` audit record so the
  regulator can confirm retention was applied.

**Regression tests:** `TestRetention`, `TestRetentionPolicyLink`.

---

## P4 — No Data Subject Access Request (DSAR) path

**Severity:** High. GDPR Art. 15 and CCPA §1798.100 entitle a subject
to a copy of their data. There was no programmatic way to produce one.

**Mitigation.**
- `stc_framework.governance.export_tenant_records(system, tenant_id)`
  walks the audit log (scoped to `tenant_id`), the trainer history
  store (scoped via `metadata.tenant_id`), and the vector store
  (via new `list_for_tenant` method), returning a single
  `DSARRecord`.
- `STCSystem.aexport_tenant(tenant_id)` provides the async facade.
- Every export is itself audited (`dsar_export` event) so the subject
  can verify the request was served.

**Regression tests:** `TestDSAR`.

---

## P5 — No right-to-erasure path

**Severity:** Critical. GDPR Art. 17 requires deletion on valid
request. Without a built-in workflow, operators were left to hand-craft
SQL/file surgery per incident — a known recipe for orphaned data.

**Mitigation.**
- `stc_framework.governance.erase_tenant(system, tenant_id)` deletes:
  - audit records matching `tenant_id`
    (`JSONLAuditBackend.erase_tenant`),
  - trainer history rows (`erase_tenant` on both the in-memory and
    SQLite stores),
  - vector-store documents (`erase_tenant` on `InMemoryVectorStore`
    + Protocol contract for custom adapters),
  - surrogate tokens (`erase_tenant` on both token stores).
- The erasure operation itself is recorded under a **null** tenant
  id so a second call does not delete the receipt.
- `STCSystem.aerase_tenant(tenant_id)` provides the async facade.

**Regression tests:** `TestErasure`.

---

## P6 — Cross-tenant leakage in shared vector store

**Severity:** Critical. The default vector store was shared across
tenants and retrieval had no tenant filter. Tenant A could upload
proprietary docs that surfaced in tenant B's retrieval.

**Mitigation.**
- `VectorStore.search` / `.keyword_search` accept a `filters` dict.
- `StalwartAgent._retrieve` passes `{"tenant_id": tenant_id}` when a
  tenant is set in the request.
- `InMemoryVectorStore` honours filters on both dense and keyword
  search.
- `list_for_tenant` and `erase_tenant` round out the Protocol so any
  adapter can implement the governance contract.

**Regression tests:** `TestTenantIsolation`, `TestDSAR.test_export_does_not_leak_other_tenants`.

---

## P7 — Indirect PII leak via retrieved chunks

**Severity:** High. A customer ingests a document that contains an
email address. A later query retrieves the chunk, and the LLM now
sees — and may echo — the email. This is a *data-leakage* problem,
not an injection problem: the attack vector is the customer's own
data.

**Mitigation.**
- `StalwartAgent._retrieve` now accepts a `chunk_redactor` (defaults
  to the Sentinel's `PIIRedactor`) and runs every retrieved chunk
  through it **before** context assembly.
- If a chunk contains a `BLOCK`-listed entity (credit card, SSN), the
  chunk is dropped rather than shipped to the LLM; a warning
  (`stalwart.chunk_dropped_blocked_pii`) lands in structured logs.
- The existing `sanitize_context_chunk` (chat-markup neutralization)
  runs in addition.

**Regression tests:**
`TestPIILeakSurface.test_retrieved_chunks_have_pii_redacted_before_llm`.

---

## P8 — Raw exception messages reflected user content

**Severity:** Medium. `StalwartAgent.arun` wrote
`result.error = f"{type(exc).__name__}: {exc}"` on any pipeline
failure. Python exception strings commonly include the argument that
triggered the error — which is exactly the user content we have spent
the rest of the pipeline trying not to persist.

**Mitigation.**
- `arun` now stores only the exception *class name*, not the message.
- The stack trace still goes to the internal structured log (under
  the existing PII-safe filter).

**Regression tests:**
`TestPIILeakSurface.test_pipeline_error_does_not_echo_exception_message`.

---

## P9 — Notifications leaked PII to third parties

**Severity:** Critical. `Notifier.alert` posted the raw `context`
dict to Slack. That dict routinely contained `tenant_id`, trigger
reasons with query fragments, etc. Pushing PII to a third-party
webhook is a notifiable breach in most jurisdictions.

**Mitigation.**
- `stc_framework.trainer.notifications._strip_pii` removes every
  field in a known-risky allow-list (`query`, `response`, `context`,
  `retrieved_chunks`, `citations`, `prompt`, `messages`, `metadata`,
  `tenant_id`, `email`, `user`, `user_id`) recursively before send.
- Slack payloads now carry the summary `message` only.
- Log output likewise receives the sanitized dict.

**Regression tests:**
`TestPIILeakSurface.test_notifier_strip_pii_removes_every_risk_field`.

---

## P10 — Trainer history store doubled as a PII reservoir

**Severity:** High. `record_from_trace` copied *every* non-aggregate
field of the trace into `HistoryRecord.metadata`. That included
`query`, `response`, `context`, and `retrieved_chunks`, so the
SQLite-backed history DB accumulated raw user content — in direct
conflict with GDPR Art. 5(1)(c) (data minimization) and the spec's
``A003_limit_data_collection`` control.

**Mitigation.**
- `record_from_trace` now filters a `_PII_RISK_FIELDS` deny-list out
  of the metadata dict.
- `tenant_id` is promoted as a top-level entry so erasure can still
  locate the row.
- `InMemoryHistoryStore.erase_tenant` / `SQLiteHistoryStore.erase_tenant`
  and `prune_before` implement the retention / erasure contract.

**Regression tests:**
`TestPIILeakSurface.test_history_record_from_trace_drops_raw_content`,
`TestRetention.test_apply_retention_prunes_history`.

---

## P11 — Hallucination: numerical claims without citations

**Severity:** High. The `NumericalAccuracyValidator` verifies numbers
exist in the source text, but it cannot detect a response that invents
the citation itself. A response like ``Revenue was $24,050 million``
(no source reference) would pass if the number happened to appear in
the context for any reason.

**Mitigation.**
- New `CitationRequiredValidator` (rail name `citation_required`)
  refuses responses that claim numbers without at least one
  `[Source: ...]` or `[Document: ...]` marker. Wired into
  `Critic.__init__` so it's always available to the spec.
- Spec authors opt in by adding the rail to
  ``critic.guardrails.output_rails``. Action defaults to ``block``.

**Regression tests:** `TestCitationRequired`.

---

## P12 — Token store lacked TTL and tenant scoping

**Severity:** Medium.

**Finding.** Surrogate tokens were retained for the lifetime of the
process, even after the data subject requested erasure or the
retention window expired.

**Mitigation.**
- `TokenStore` Protocol gains `erase_tenant(tenant_id)` and
  `prune_before(cutoff)`.
- `InMemoryTokenStore` and `EncryptedFileTokenStore` both implement
  them.
- `Tokenizer.tokenize(value, tenant_id=...)` threads tenant scope
  through so the erasure workflow can target entries.
- Token entries now carry `created_at` so retention can prune them.

**Regression tests:** `TestTokenStoreGovernance`.

---

## Regulatory cross-walk

| Regulation / Control | How this framework satisfies it |
|---|---|
| **GDPR Art. 5(1)(c) — data minimization** | `record_from_trace` filters PII-risk fields; `notifications._strip_pii` strips them from outbound alerts. |
| **GDPR Art. 5(1)(e) — storage limitation** | `governance.apply_retention` prunes audit, history, tokens. |
| **GDPR Art. 15 / CCPA §1798.100 — right of access** | `governance.export_tenant_records` / `STCSystem.aexport_tenant`. |
| **GDPR Art. 17 — right to erasure** | `governance.erase_tenant` / `STCSystem.aerase_tenant`. |
| **GDPR Art. 25 — data protection by default** | Presidio redaction on ingress; chunk redaction on egress; hash-chained audit. |
| **GDPR Art. 30 — records of processing** | Tamper-evident audit covers every processing event. |
| **GDPR Art. 32 — security of processing** | Encrypted token store; PII-safe logs; injection / ReDoS defences. |
| **SOC 2 CC7.2 / CC7.3 — logging and monitoring** | Comprehensive `AuditEvent` catalogue; Prometheus metrics; OpenTelemetry traces. |
| **SOC 2 CC8.1 — change management** | `prompt_registered` / `prompt_activated` / `routing_updated` audit events. |
| **SOC 2 CC9.2 — vendor management** | Adapter Protocol interface makes every external integration swappable and auditable. |
| **HIPAA §164.312(b) — audit controls** | Append-only, hash-chained audit log. |
| **HIPAA §164.312(c) — integrity** | `verify_chain` detects unauthorized modification. |
| **HIPAA §164.312(e) — transmission security** | Sentinel enforces TLS via LiteLLM; restricted-tier data never leaves in-boundary models. |
| **AIUC-1 A001–A007** | Sentinel layer; data-tier routing; Presidio; tokenization; virtual keys. |
| **AIUC-1 E_audit_trail** | Immutable audit log with chain verification. |
| **AIUC-1 E_human_oversight** | `DegradationState.QUARANTINE` holds responses for human review. |

---

## Residual risks (out of library scope)

1. **Third-party sub-processors.** Cloud LLM providers still receive
   redacted query text. Customers must sign DPAs with them directly;
   the framework cannot do that on their behalf.
2. **Infrastructure-level access.** A root compromise of the host
   reading the audit log file can still read (though not silently
   alter) history. Deploy write-once storage (S3 Object Lock,
   Immudb, or equivalent) for production audit retention.
3. **Prompt-injection arms race.** Novel attacks appear constantly;
   keep `stc_framework.security.injection.INJECTION_RULES` and
   `test_security.py::TestInjectionDetection` updated as new
   bypasses are disclosed.
4. **Schema evolution.** `AuditRecord` is pydantic-versioned; rotating
   fields must go through a controlled deprecation to keep old chains
   verifiable.

## Running the audit

```bash
pip install -e ".[dev,service]"
pytest tests/unit/test_privacy.py -v
pytest tests/unit/test_security.py -v
```

Any failure in either file is a release blocker.
