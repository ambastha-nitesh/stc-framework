# Architecture Decision Records

Five decisions that shape everything in this codebase. Each one is a
call that a reasonable senior could have made the opposite way; the
"why not X" half matters as much as the choice.

Format: [Michael Nygard ADR](https://adr.github.io/madr/).

---

## ADR-001 — Three personas as **structural roles**, not cooperating agents

### Status
Accepted.

### Context
An agent system needs to do three things: execute business tasks,
evaluate outputs, and improve over time. The obvious design is "one
smart agent that does all three with different prompts," which is what
most frameworks ship.

### Decision
We split execution (**Stalwart**), optimization (**Trainer**), and
governance (**Critic**) into distinct modules with *asymmetric
authority*. A Stalwart cannot evaluate its own output. A Critic cannot
rewrite a response — only verdict. A Trainer cannot change runtime
behavior directly; it writes through the Sentinel and the prompt
registry.

### Why not "one LLM with system prompts for each role"
- A single model that both answers and grades itself has unavoidable
  confirmation bias — it will rationalize its own hallucinations. Many
  papers confirm this; we also confirmed it in our own eval.
- A single process that "is" all three roles cannot give a regulator
  separation of duties (SOX 404, SEC §205.3). If the same code path
  writes a response and stamps "approved", no audit will pass.
- Separation makes testing tractable. Each persona has a focused
  contract; we can build evidence about one without perturbing the
  others.

### Tradeoffs we accept
- More code surface: four modules instead of one.
- More integration tests to keep the planes honest.
- Extra latency from output rails (typically ~1 ms with mocks, more
  with real validators).

---

## ADR-002 — Adapter-as-Protocol with zero-install defaults

### Status
Accepted.

### Context
The framework needs to interop with: an LLM provider (Anthropic /
OpenAI / Ollama / LiteLLM / Bedrock), a vector store (Qdrant / pgvector
/ Weaviate), an embedder, a prompt registry (Langfuse / in-house), an
audit sink (local file / S3 / Immudb / Splunk). Any hard dependency on
one vendor would kill adoption.

### Decision
Every external surface is a `typing.Protocol`. We ship a working
in-memory default for every one (mock LLM, hash embedder, in-memory
vector store, file prompt registry, JSONL audit backend). Real vendor
adapters are optional installs (`[litellm]`, `[qdrant]`, `[langfuse]`, …).

### Why not abstract base classes or plugins via entry points
- ABCs force inheritance; Protocols are structural and compose with
  duck-typed test doubles cleanly.
- Entry-point plugins are great for downstream extension but obscure
  the type contract; we want new contributors to read one file to
  understand what an adapter must satisfy.
- Zero-install defaults let `pip install stc-framework && python -c
  'from stc_framework import STCSystem; STCSystem.from_env()'` actually
  work for 80% of first-impressions without pulling 1 GB of spaCy
  models.

### Tradeoffs we accept
- The mock LLM is load-bearing for tests but a foot-gun in prod.
  Mitigated by `STC_ENV=prod` explicitly refusing `STC_LLM_ADAPTER=mock`.
- Adapter evolution needs care: any new method on a Protocol is a
  breaking change for every implementor. We mark optional methods as
  default-implementing returning sensible zeros.

---

## ADR-003 — The **spec is the compliance posture**, signed and versioned

### Status
Accepted.

### Context
Auditors don't want to read Python. They want a single artifact that
answers "what rails are running?", "what data tier goes to which
model?", "what retention applies?". They want to diff last quarter's
artifact against this quarter's.

### Decision
`stc-spec.yaml` is the single source of truth for every runtime policy.
Under `STC_ENV=prod` it must carry an ed25519 signature verified
against `STC_SPEC_PUBLIC_KEY`. Every mutation is recorded in the audit
log with the content hash.

### Why not a database-backed config service with an admin UI
- A runtime-mutable config service is a permanent insider-threat
  attack surface. An admin UI bug becomes a compliance incident.
- Git history + signed files gives us version control, diffability,
  and non-repudiation without building our own auditor.
- An operator responding to an incident can read and reason about
  a 200-line YAML. They cannot reason about an admin UI's state in the
  same way.

### Tradeoffs we accept
- Changes require a redeploy. That's a feature for regulated envs.
- Canary / percentage rollouts need separate tooling (roadmap item).
- Two specs for two tenants means two processes, unless we extend the
  Protocol. We've chosen to extend later rather than prematurely.

---

## ADR-004 — HMAC-chained audit with class-specific retention, WORM-optional

### Status
Accepted.

### Context
SEC 17a-4(f) requires broker-dealer records to be WORM. GDPR Art. 17
requires erasure on request. These are in direct tension for records
that are both "regulated" and "contain PII".

### Decision
1. Audit records are chained via HMAC-SHA256 with a per-deployment
   key. An attacker with write access but not key access cannot forge.
2. Two backends: `JSONLAuditBackend` (GDPR-friendly, supports
   `erase_tenant` by rewriting the chain) and `WORMAuditBackend`
   (SEC-friendly, refuses prune/erase with `ComplianceViolation`).
3. Retention is per-event-class: `erasure` receipts, DSAR exports,
   boundary crossings, escalation transitions default to 6 years;
   chain-seal records to *forever*; regular queries to the spec
   default.
4. The deployer picks one backend. GDPR-primary deployments use the
   JSONL backend with tokenization so that deleting a tenant's tokens
   cryptographically renders their audit records pseudonymous without
   rewriting them.

### Why not a signed-blockchain append-only log, or a DB-backed audit
- A blockchain is operationally heavier than our audience can
  afford.
- A DB backend is a perfect choice, but it's not what ships out of the
  box; we ship local files so the reference implementation has no
  infra dependency.
- Both are writable via the `AuditBackend` Protocol. The adapter story
  holds.

### Tradeoffs we accept
- Non-regulated customers pay the HMAC cost (~5 µs per record) even
  when they don't need it. Worth it for consistency.
- "WORM but at the application layer" is necessary-not-sufficient;
  operators must combine with OS-level immutability (S3 Object Lock,
  Linux `chattr +a`, Immudb) for real compliance.

---

## ADR-005 — Async-first with sync facade; contextvars for correlation

### Status
Accepted.

### Context
Every real I/O path (LLM, vector, embeddings, audit) has multi-hundred-
millisecond tails. If the Stalwart runs these serially in a sync
function, a 10 QPS service needs 50+ workers. If we push async all the
way down, library users who aren't async-aware struggle.

### Decision
- The real pipeline is async (`aquery`, `acompletion`, `aemb`, …).
- A sync facade `STCSystem.query` exists purely for convenience in
  notebooks and simple scripts; it refuses to run inside a running
  event loop.
- Correlation (trace_id, tenant_id, persona) is propagated via
  `contextvars.ContextVar`, not through function arguments. Logs and
  spans read them automatically.

### Why not fully sync with a thread pool, or split the library in two
- Thread pools limit concurrency by CPU count; async gives us 10k+
  concurrent outbound calls on one worker for pure I/O.
- Two libraries would double the test and docs burden with no
  substantive win; the sync facade is 20 lines.
- `contextvars` is the standard pattern now; threading it through
  every function would be a maintenance tax for no benefit.

### Tradeoffs we accept
- First-time readers must understand `asyncio.to_thread` when they hit
  Presidio / SQLite / the JSONL audit writer — those are synchronous
  and we pay the thread-pool hop. Documented in GOTCHAS.
- `contextvars` plus `asyncio` interact subtly under `asyncio.gather`
  with parent-task mutation — we pin versions and test the behaviour.
