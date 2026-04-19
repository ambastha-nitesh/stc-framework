# Glossary

Assume general CS knowledge, zero business context. Terms are grouped
by domain.

## STC-specific

- **Stalwart** — The execution persona. Runs the RAG pipeline
  (classify → retrieve → reason) and nothing else. Never evaluates its
  own output.
- **Trainer** — The optimization persona. Observes traces, computes
  rewards, proposes routing/prompt changes. Never runs a business
  task itself.
- **Critic** — The zero-trust governance persona. Verifies every
  Stalwart output against rails. Can block or warn but never edits a
  response.
- **Sentinel** — The infrastructure layer (*not* an agent). Enforces
  data-tier routing, PII redaction, tokenization, audit.
- **Rail** — A single named validator that runs over input or output.
  Identified by `rail_name` (a string constant in the validator class).
- **Spec** — The declarative YAML (`stc-spec.yaml`) that defines every
  rail, cost threshold, routing policy, and retention rule. The
  single source of truth for compliance posture.
- **Persona key** — A virtual key issued per persona so audit logs
  record which plane made a given call. Not related to cryptographic
  key rotation of the audit HMAC.
- **Boundary crossing** — An LLM call from a restricted-tier query to
  a non-local model. Automatically audited; also metered. A
  misconfigured deployment can have zero if restricted traffic is
  routed locally.
- **Escalation** — The Critic's four-state machine: `NORMAL →
  DEGRADED → QUARANTINE → PAUSED`. Driven by recent rail-failure
  counts and consecutive-failure counts.

## Governance / regulatory

- **AIUC-1** — *AI Usage and Compliance 1*, an industry certification
  framework for AI agents. Our `compliance.aiuc_1` spec block maps
  controls to implementation.
- **FINRA 4511** — *Financial Industry Regulatory Authority* rule
  mandating broker-dealer books-and-records retention for at least 6
  years.
- **SEC 17a-4** — US Securities and Exchange Commission rule requiring
  electronic records be stored WORM (write-once, read-many).
- **MNPI** — *Material Non-Public Information*. Regulated by Regulation
  FD and insider-trading laws. Our rails do not currently detect it;
  see `CONTRIBUTING.md` "add a rail" guide for the canonical example.
- **SOX 404** — *Sarbanes-Oxley Section 404*, internal controls over
  financial reporting. Requires change-control / separation of duties.
- **GDPR Art. 15 / 17** — *Right of access* and *right to erasure*.
  Implemented via `governance.export_tenant_records` and
  `governance.erase_tenant`.
- **DSAR** — *Data Subject Access Request*. The formal name for a
  GDPR Art. 15 export.
- **WORM** — *Write Once, Read Many*. Storage that refuses mutation
  or deletion. SEC 17a-4 requires this for broker-dealer records.
- **NYDFS Part 500** — New York Department of Financial Services
  cybersecurity regulation; applies to financial services in NY.
- **MiFID II** — *Markets in Financial Instruments Directive II*; EU
  regulation with its own record-keeping rules.
- **KYC** — *Know Your Customer*. Identity verification records with
  their own retention requirements (typically 5 years
  post-account-closure).
- **Legal hold** — Litigation-driven retention override. Our
  framework does not automatically suspend retention during legal
  holds; roadmap item.

## Machine learning / AI

- **RAG** — *Retrieval-Augmented Generation*. The Stalwart pattern:
  retrieve relevant chunks from a vector store, then reason over them
  with an LLM.
- **Prompt injection** — An attack where user input hijacks the
  model's instructions. Mitigated by input rails + sanitizers.
- **Indirect prompt injection** — Same attack but via retrieved
  documents the user uploaded. Mitigated by chunk sanitization.
- **Hallucination** — A model response containing claims not supported
  by the provided context. Mitigated by grounding validators.
- **GRPO** — *Group Relative Policy Optimization*, an RL algorithm used
  by Agent Lightning. Declared in the spec but the default
  `InMemoryRecorder` just collects transitions without training.
- **HMAC-SHA256** — Keyed hash function. Used for our audit chain —
  HMAC means an attacker with file access but no key cannot forge.
- **Ed25519** — Asymmetric signature scheme used to sign the spec
  file. Public key pinned via `STC_SPEC_PUBLIC_KEY`.

## Operational

- **Bulkhead** — A concurrency limiter per downstream; one slow
  dependency cannot exhaust the event loop.
- **Circuit breaker** — A state machine around an external call that
  opens after repeated failures, short-circuits traffic for a cooldown,
  then half-opens to probe.
- **Data tier** — A classification level (`public`, `internal`,
  `restricted`) assigned per query. Drives which models are allowed.
- **Surrogate tokenization** — Replacing a PII value with an opaque
  reversible token (e.g. `STC_TOK_abc123`). Lets us route sensitive
  data through cloud models by substituting tokens, then detokenize
  the response.
- **Rolling bucket budget** — Per-tenant daily cost tracking in
  calendar-day buckets (resistant to wall-clock jumps).
- **Idempotency key** — A client-supplied identifier that makes a retry
  safe — the same key returns the same cached `QueryResult`.
- **Rail result evidence** — A dict of validator-specific diagnostic
  info attached to a `GuardrailResult`. Not a freeform blob — see
  individual validators for the shape.
- **Degradation state** — The `NORMAL | DEGRADED | QUARANTINE | PAUSED`
  flag. Observable via `/readyz` and `stc_escalation_level`.

## Repo / tooling

- **Rail index** — The cached `dict[str, Validator]` built once per
  `STCSpec` for O(1) lookup. Memoized via `object.__setattr__`.
- **`_KeyManager`** — The HMAC-key singleton for audit chain sealing.
  Not the same as token-store keys.
- **`_SystemRunner`** — The Flask service's bridge between WSGI (sync)
  and `STCSystem` (async). One dedicated asyncio thread per worker.
- **Strict prod mode** — `STC_ENV=prod`. Enforces 6 invariants at
  startup that collectively prevent dev settings from reaching
  production.
