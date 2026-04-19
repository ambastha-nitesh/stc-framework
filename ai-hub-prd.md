# AI Hub — Product Requirements Document

**Version:** 1.0 (Draft for architecture and engineering sign-off)
**Audience:** Architects, backend engineers, QA/SDET, security, compliance, domain leads
**Last updated:** April 19, 2026

---

## Reading guide

Each functional requirement in section 4 follows the same structure: an **Overview** in prose that explains the requirement and its design rationale; **Preconditions** that must hold; detailed **Inputs** and **Outputs**; a **Happy-path narrative** written as prose (not bullets); **Exception paths** enumerated as `E<FR>.<n>` with named *trigger*, *detection*, *behavior*, *observable outcome*, and *audit* fields; **Side effects** describing the state changes; and **Acceptance criteria** in testable `AC-<FR>.<n>` form.

Architects should read sections 1–3, 5, 9, 10, and the Overview of each FR. Engineers should read 4, 5, 6, 8, 11. QA/SDET should focus on the ACs in section 4 and test plans in 11.

---

## Table of contents

1. [Overview and goals](#1-overview-and-goals)
2. [System architecture](#2-system-architecture)
3. [Personas and roles](#3-personas-and-roles)
4. Functional requirements
   - [4.1 FR-1 — Model access and routing](#41-fr-1--model-access-and-routing)
   - [4.2 FR-2 — Edge authentication](#42-fr-2--edge-authentication)
   - [4.3 FR-3 — Input filter chain](#43-fr-3--input-filter-chain)
   - [4.4 FR-4 — Machine-to-machine authentication](#44-fr-4--machine-to-machine-authentication)
   - [4.5 FR-5 — Output filter chain](#45-fr-5--output-filter-chain)
   - [4.6 FR-6 — Role-based access control](#46-fr-6--role-based-access-control)
   - [4.7 FR-7 — Domain onboarding](#47-fr-7--domain-onboarding)
   - [4.8 FR-8 — Agent onboarding and starter kit](#48-fr-8--agent-onboarding-and-starter-kit)
   - [4.9 FR-9 — Rate limits and spend caps](#49-fr-9--rate-limits-and-spend-caps)
   - [4.10 FR-10 — Per-agent model allowlist](#410-fr-10--per-agent-model-allowlist)
   - [4.11 FR-11 — Platform engineer dashboard](#411-fr-11--platform-engineer-dashboard)
   - [4.12 FR-12 — Domain owner dashboard](#412-fr-12--domain-owner-dashboard)
   - [4.13 FR-13 — Audit ledger](#413-fr-13--audit-ledger)
   - [4.14 FR-14 — Fail-behavior contract](#414-fr-14--fail-behavior-contract)
5. [Data model](#5-data-model)
6. [API contracts](#6-api-contracts)
7. [Non-functional requirements](#7-non-functional-requirements)
8. [Observability specification](#8-observability-specification)
9. [Security specification](#9-security-specification)
10. [Deployment and environments](#10-deployment-and-environments)
11. [Testing and acceptance](#11-testing-and-acceptance)
12. [Rollout plan](#12-rollout-plan)
13. [Success metrics](#13-success-metrics)
14. [Assumptions and open questions](#14-assumptions-and-open-questions)
15. [Glossary](#15-glossary)
- [Appendix A — Error code catalog](#appendix-a--error-code-catalog)
- [Appendix B — Complete permissions matrix](#appendix-b--complete-permissions-matrix)
- [Appendix C — Audit record JSON schema](#appendix-c--audit-record-json-schema)

---

## 1. Overview and goals

### 1.1 Problem statement

Business units across the organization are building LLM-powered agents directly against AWS Bedrock. Each team independently implements authentication, prompt-injection defenses, PII scrubbing, content policy enforcement, cost controls, and audit capture. The result is inconsistent enforcement posture, duplicated engineering effort, no centralized visibility for Security and Compliance, and no way to enforce organization-wide controls such as model allowlists or spend caps.

Direct access to Bedrock also creates a set of operational risks that are invisible until they materialize. A misconfigured agent can exhaust a Bedrock quota shared by other workloads. A developer can accidentally send production PII to a model without realizing the prompt is logged by the underlying provider's safety systems. A malicious prompt can exfiltrate a system prompt that encodes proprietary business logic. None of these failure modes is easily preventable when every consuming team writes their own integration.

### 1.2 Solution summary

AI Hub is an AI Control Plane that mediates all LLM traffic between registered agents and AWS Bedrock. It is composed of two cooperating layers: **Kong AI Gateway** as the data plane for ingress, TLS termination, authentication, and coarse rate limiting; and a set of **AI Hub control-plane services** that handle registration, entitlement, guardrails, audit capture, and dashboards.

Every inference request is authenticated at the edge, authorized against the calling agent's entitlements, filtered through an input guardrail chain, forwarded to Bedrock, filtered through an output guardrail chain, and written synchronously to a domain-partitioned immutable audit ledger. The same request payload, response payload, filter verdicts, token counts, and cost are always written to the ledger — there is no code path through AI Hub that produces an unlogged Bedrock invocation.

AI Hub is intended to be the only supported path to Bedrock for production agents. As part of rollout, direct Bedrock access from application AWS accounts is removed at the network layer through a combination of Service Control Policies at the organizational unit boundary and VPC endpoint policies that allow traffic only from the AI Hub production account.

### 1.3 In-scope for MVP

MVP delivers:

- A unified, **non-streaming** REST API in front of AWS Bedrock.
- **OAuth 2.0 / OIDC** edge authentication via Ping Identity for both human users and agent runtime identities.
- An **input guardrail chain**: prompt-injection detection, PII scanning, content-policy evaluation.
- An **output guardrail chain**: PII scrub, harmful-content detection, policy-compliance evaluation.
- **Self-service onboarding** for domains and agents with human-in-the-loop approval.
- **RBAC** across five roles: Platform Admin, Domain Admin, Agent Developer, Agent Runtime, Auditor.
- **Dashboards** for platform engineers and domain owners.
- A **domain-partitioned immutable audit ledger** with an extract capability.
- **Token-based per-agent rate limits** (RPM, TPM) and **per-domain monthly USD spend caps**.
- **Per-agent model allowlist** with default-deny.
- Explicit **fail-open / fail-closed behavior** for every dependency.
- A defined **latency budget**: p95 hub overhead ≤ 800 ms.

### 1.4 Out of scope for MVP

The following are deliberately deferred:

- **Streaming responses** (`InvokeModelWithResponseStream`). Applying output filters to a token stream has correctness implications (specifically how to revoke already-streamed tokens when a filter fires late) that require dedicated design.
- **Multi-provider routing** to non-Bedrock providers. The abstraction is in place; only Bedrock is wired.
- **Multi-modal guardrails** for images and audio. MVP Bedrock Guardrails sensitive-information detectors are text-only.
- **Semantic caching**, **prompt registries** with versioning, **red-team anomaly detection**, and **HITL override** workflows.
- **First-class tool-use / function-calling** semantics. In MVP, `tool_use` and `tool_result` blocks are passed through as opaque text and receive the same filter treatment as any other text content.
- **Chargeback billing** with invoicing. Raw token and cost data are in the ledger; finance may extract from it.
- **Custom per-domain filter policies**. Platform policy is globally uniform in MVP.

### 1.5 Goals

AI Hub is successful in MVP if five goals are met:

1. **Exclusive path to Bedrock.** AI Hub becomes the only supported path for all production agents within 180 days of GA, verified by CloudTrail reconciliation against hub audit records.
2. **Uniform guardrail enforcement with zero per-domain burden.** A domain's total integration work fits in the starter kit and is completable in hours, not weeks.
3. **Single audit surface.** Security and Compliance have one queryable surface covering 100% of LLM traffic.
4. **Low hub overhead.** p95 hub overhead ≤ 800 ms, so domains don't regret using AI Hub on latency grounds.
5. **Fast time-to-value.** Domain registration → first successful Bedrock call ≤ 1 business day. Agent registration → first call ≤ 2 hours.

### 1.6 Non-goals

AI Hub does not provide prompt engineering, agent orchestration, or chain-of-thought frameworks. It does not host models directly — it is a gateway to Bedrock. It does not manage upstream data stores, vector databases, or RAG pipelines. It does not provide chargeback billing in MVP.

---

## 2. System architecture

### 2.1 Logical architecture

The system is organized as two planes. The **data plane** — Kong AI Gateway — handles the edge concerns: TLS termination, JWT validation against Ping, coarse request-rate limiting, and routing. The **control plane** — a set of AI Hub services — handles the domain-specific concerns: entitlement checking, guardrail orchestration, Bedrock invocation, audit capture, registration workflows, and dashboards.

Every inference request follows the same path. A caller (human user or agent runtime process) obtains an OAuth 2.0 access token from Ping. The caller sends the token in the `Authorization` header to the Kong public endpoint. Kong validates the JWT, applies edge rate limiting, injects a correlation identifier, and routes to AI Hub Core. Core performs entitlement checks, orchestrates the input filter chain, invokes Bedrock via the Model Router, orchestrates the output filter chain, and writes the audit record synchronously. Only then is the response returned.

```
┌──────────────┐   ┌─────────────────────────────────────────────┐
│ Agent / User │──▶│ Kong AI Gateway (edge, data plane)          │
│   Caller     │   │ • Ping JWT validation                       │
└──────────────┘   │ • Request-rate limit (RPM)                  │
                   │ • Correlation ID injection                  │
                   │ • Route to AI Hub Core                      │
                   └──────────────────────┬──────────────────────┘
                                          │
                   ┌──────────────────────▼──────────────────────┐
                   │ AI Hub Core API (control plane)             │
                   │                                             │
                   │  1. Entitlement Service                     │
                   │     • Agent/domain state check              │
                   │     • Model allowlist check (FR-10)         │
                   │     • TPM counter projection (FR-9)         │
                   │     • Spend-cap projection (FR-9)           │
                   │                                             │
                   │  2. Input Filter Chain (sequential)         │
                   │     • Prompt injection detector             │
                   │     • PII scanner                           │
                   │     • Content policy evaluator              │
                   │                                             │
                   │  3. Model Router (Bedrock client)           │
                   │     • Logical model_id → ARN resolution     │
                   │     • AWS IAM role assumption               │
                   │     • InvokeModel with 30s timeout          │
                   │                                             │
                   │  4. Output Filter Chain (sequential)        │
                   │     • PII scrub                             │
                   │     • Harmful content detector              │
                   │     • Policy compliance evaluator           │
                   │                                             │
                   │  5. Audit Writer (synchronous)              │
                   │     • Payload → S3 Object Lock (WORM)       │
                   │     • Index → OpenSearch                    │
                   │     • Usage → Redis TPM counter             │
                   └──────────────────────┬──────────────────────┘
                                          │
                   ┌──────────────────────▼──────────────────────┐
                   │ AWS Bedrock (InvokeModel)                   │
                   └─────────────────────────────────────────────┘
```

### 2.2 Out-of-band supporting services

The request-path components above are supported by services that do not sit on the synchronous request path but provide essential capabilities:

- **Registration Service** — owns domain/agent onboarding workflows, invoked from dashboard UIs.
- **Dashboard API** — serves read-only aggregates to platform and domain dashboards.
- **Policy Store** — holds versioned content policy, PII category configuration, model catalog, and Bedrock pricing.
- **Audit Payload Store** — S3 bucket with Object Lock (Compliance mode), encrypted per-domain payloads.
- **Audit Index** — OpenSearch cluster, searchable metadata records (without payloads).
- **Rate-limit Store** — ElastiCache Redis cluster, sliding-window token buckets.
- **Ping Identity** — sole IdP, all user and agent credentials.
- **AWS Secrets Manager** — service-to-service credentials and third-party API keys.
- **AWS KMS** — per-domain customer-managed keys for payload encryption.

### 2.3 Component responsibilities

| Component | Responsibility | Technology (MVP) |
|---|---|---|
| Kong AI Gateway | Edge termination, TLS, JWT validation, RPM limit, correlation-ID, routing. | Kong Gateway 3.x + AI plugins |
| AI Hub Core API | Orchestrates entitlement, filters, model router, audit. Stateless. | Python 3.12 + FastAPI on ECS Fargate |
| Entitlement Service | Allowlist, TPM/spend projection, state checks. In-process within Core. | Embedded module; Postgres + Redis |
| Input/Output Filter Chain | Runs guardrail filters sequentially via common interface. | Bedrock Guardrails (primary), Comprehend (PII fallback) |
| Model Router | Logical ID → Bedrock ARN; `InvokeModel` call; error translation. | AWS SDK (boto3) |
| Audit Writer | Synchronous S3 + OpenSearch writes. Embedded in Core. | Embedded |
| Registration Service | Domain/agent state machines, approvals, starter-kit generation. | Python + Postgres |
| Dashboard API | Read APIs for dashboards. | Python + Postgres read replicas + OpenSearch |
| Policy Store | Versioned platform policies, catalog, pricing. | Postgres + Flyway |
| Rate-limit Store | RPM/TPM counters. | ElastiCache for Redis (cluster mode) |
| Audit Payload Store | Encrypted per-domain KMS; S3 + Object Lock. | S3 + KMS |
| Audit Index | Queryable metadata. | OpenSearch Service |
| Identity Provider | All OAuth 2.0 / OIDC tokens. | Ping Identity |

### 2.4 End-to-end request lifecycle (happy path)

The following narrative walks through a successful inference request. It is referenced throughout the functional requirements.

The caller begins by obtaining an OAuth 2.0 access token from Ping. Human users use the authorization-code flow with PKCE. Agent runtime processes use the client-credentials flow with the `client_id` and `client_secret` issued at agent onboarding. The resulting JWT contains, at minimum, `iss`, `aud`, `exp`, `iat`, `sub`, `scope`; agent tokens additionally contain `domain_id`, `agent_id`, and `client_id`.

The caller sends the JWT as a Bearer token to `POST https://aihub.<env>.example.com/v1/inference` with a JSON body containing `model_id`, `messages`, and optional `system` and `inference_params`. The request arrives at Kong.

Kong validates the JWT by verifying its signature against the currently cached Ping JWKS, checking `iss`, `aud` = `"aihub"`, `exp` in the future (±60s clock skew), and that the token includes scope `aihub:invoke`. If any validation fails, Kong returns 401 or 403 immediately. Assuming validation passes, Kong applies the per-agent RPM limit via a sliding-window counter in Redis; if exceeded, 429 with `Retry-After`. Kong generates a ULID, sets it as `X-AIHub-Request-Id`, and forwards to AI Hub Core.

Core API receives the request and parses the body against the input JSON schema. It extracts the `agent_id` claim, loads the agent record from Postgres (joined with domain and allowlist), verifies `state = ACTIVE` for both agent and domain. The Entitlement Service checks: (a) `model_id` is in the allowlist; (b) projected TPM (current-window + input estimate + `max_tokens`) does not exceed the limit; (c) projected USD cost does not push monthly spend over the domain cap. Any failure short-circuits before any filter runs.

The Input Filter Chain runs in order prompt-injection → PII → content-policy. Each filter has a 300ms timeout and returns `ALLOW`, `BLOCK`, or `ERROR`. First non-`ALLOW` short-circuits.

The Model Router translates the logical `model_id` to the Bedrock ARN (from Policy Store), acquires AWS credentials via IAM role assumption, and calls `InvokeModel` with a 30-second timeout. On success, it extracts the completion, `stop_reason`, and usage counts.

The Output Filter Chain runs in order PII-scrub → harmful-content → policy-compliance on the completion text, same semantics.

If all output filters `ALLOW`, the Audit Writer composes the audit record. It encrypts the combined request+response payload using envelope encryption (fresh data key, wrapped by per-domain KMS CMK) and uploads to S3 at `s3://<bucket>/audit/v1/domain=<domain_id>/date=<yyyy-mm-dd>/request_id=<ulid>.json.enc` with Object Lock set to the configured retention. Concurrently indexes the metadata to OpenSearch. Both writes must succeed; failure returns 503.

Rate-limit Store is updated: Redis `INCRBY` for the TPM counter with actual tokens (overwriting the projection contribution). Postgres month-to-date spend for the domain is updated.

Core emits the 200 response with body (completion, usage, latency) and headers (`X-AIHub-Request-Id`, `X-AIHub-Tokens-Used`, rate-limit headers). End-to-end typically 1–3 seconds depending on model and prompt length.

From the caller's perspective, a single synchronous HTTP request. From the operator's perspective, exactly one row in the audit index, exactly one object in the payload store, incremented counters, zero other side effects.

### 2.5 Environments

| Environment | Purpose | Isolation |
|---|---|---|
| `dev` | Engineering development of AI Hub itself. | Separate AWS account; non-prod Ping tenant. |
| `sandbox` | Agent developers test against real AI Hub with mock Bedrock. | Separate AWS account; Bedrock replaced by deterministic mock. |
| `staging` | Pre-production integration; real Bedrock, smaller limits. | Separate AWS account; non-prod Ping tenant. |
| `prod` | Production traffic. | Dedicated AWS account; prod Ping tenant. |

---

## 3. Personas and roles

### 3.1 Personas

**Platform Admin (human).** A member of the Platform Engineering team that operates AI Hub itself. Platform Admins approve new domain registrations, manage platform-wide policies (content policy, PII category configuration, model catalog, default spend caps by tier), approve restricted-tier model requests, override spend caps, suspend domains or agents in emergencies, and have global read access across all data including audit ledgers in all partitions.

**Domain Admin (human).** The primary or secondary owner of an onboarded domain. Domain Admins approve agent registrations within their domain, manage agents' allowlists (within the domain's eligibility tier), rotate or revoke agent credentials, adjust RPM/TPM on agents (within domain ceilings), and have full read access to data within their own partition only. They cannot read or act on another domain's data.

**Agent Developer (human).** A developer who builds and operates one or more specific agents. Agent Developers submit agent registration requests, rotate their own agent's credentials, submit allowlist-change requests, and have read access to the domain dashboard scoped to agents they own or co-own. They do not approve registrations and cannot see other agents' details.

**Agent Runtime (machine).** The running agent process that invokes `POST /v1/inference`. Agent Runtime is a Ping OAuth client issued at agent onboarding, with only the `aihub:invoke` scope. It has no dashboard access. Any token minted through client-credentials grant carries only the Agent Runtime role regardless of any claim-manipulation attempt.

**Auditor (human).** A member of Security or Compliance with read-only access to the audit ledger. Auditors may be globally scoped (all domains) or domain-scoped (a specified subset). They can run audit extracts within their scope but cannot modify any configuration, agent, or domain.

### 3.2 Role sourcing

Roles for human users are sourced from Ping Identity group memberships. Each AI Hub role corresponds to a specific Ping group; membership is surfaced as an entry in the `roles[]` claim. AI Hub does not maintain its own role store and does not provide a UI for role assignment — all role changes go through Ping provisioning.

For machine identities (Agent Runtime), roles are implicit. Any token issued via client-credentials grant carries only the Agent Runtime role. This is enforced at Ping by policy on the client configuration.

Role changes take effect on next token refresh. Since access tokens have a 1-hour maximum lifetime, changes are effective within 1 hour. Emergency role removal is achieved by revoking the Ping session or disabling the OAuth client (immediate token invalidation, within its 1-hour grace).

### 3.3 Summary permission matrix

Complete matrix in [Appendix B](#appendix-b--complete-permissions-matrix).

| Capability | Plat. Admin | Dom. Admin | Agent Dev | Agent Runtime | Auditor |
|---|:-:|:-:|:-:|:-:|:-:|
| Approve domain registration | ✓ | — | — | — | — |
| Approve agent registration (Standard models) | ✓ | ✓ | — | — | — |
| Approve agent registration (Restricted models) | ✓ | Acknowledge | — | — | — |
| Submit agent registration | ✓ | ✓ | ✓ | — | — |
| Invoke `/v1/inference` | — | — | — | ✓ | — |
| Rotate agent client secret | ✓ | ✓ (any in domain) | ✓ (own) | — | — |
| View platform dashboard | ✓ | — | — | — | — |
| View domain dashboard | ✓ (any) | ✓ (own) | ✓ (own agents) | — | — |
| Read audit ledger | ✓ (any) | ✓ (own) | — | — | ✓ (per scope) |
| Override spend cap | ✓ | — | — | — | — |

---

## 4. Functional requirements

Every functional requirement in this section follows the same structure: **Overview** (prose rationale), **Preconditions**, **Inputs/Outputs**, **Happy-path narrative**, **Exception paths** (`E<FR>.<n>` with trigger/detection/behavior/observable/audit), **Side effects**, and **Acceptance criteria** (`AC-<FR>.<n>` in testable form).

Wherever text refers to "the caller", the intent is the principal identified by the JWT — either a human user authenticated through authorization-code flow or a machine identity authenticated through client-credentials flow. "Domain" and "Agent" refer to the corresponding Postgres records in section 5. "Audit record" refers to the canonical JSON schema in Appendix C.

---

### 4.1 FR-1 — Model access and routing

#### 4.1.1 Overview

The model access and routing feature is the primary inbound request surface. Its purpose is to give every calling agent a single, stable HTTP contract that does not change when the underlying model provider mix evolves. Although Bedrock is the only supported provider in MVP, the API is designed such that adding Azure OpenAI, Google Vertex, or a self-hosted provider in v2 does not require a breaking schema change for existing agents.

The abstraction is deliberately narrow. AI Hub does not expose the full surface area of Bedrock's Converse or InvokeModel APIs; it exposes a curated subset that covers the inference patterns used by the vast majority of agent workloads: synchronous, text-based chat completion with an optional system prompt and standard inference parameters. Tool use and function-calling content blocks are passed through as opaque text in MVP and receive the same filter treatment as any other text content. Streaming is explicitly out of scope because applying output filters to a token stream has correctness implications that require dedicated design.

The model identifier presented to callers is a logical identifier maintained by AI Hub in the Policy Store, not a Bedrock model ARN. This layer of indirection exists for three reasons. First, callers do not have to change code when AWS publishes a new minor version of a model or when AI Hub migrates between inference profiles. Second, AI Hub can enforce a model catalog with tier metadata (Standard vs. Restricted) that is divorced from Bedrock's naming. Third, future routing decisions — for example, routing `claude-sonnet-4-6` calls from an EU-classified domain to an `eu-west-1` inference profile — can be made inside AI Hub without any caller change.

The endpoint is stateless and idempotent in behavior at the HTTP layer, but deliberately does not provide idempotency keys in MVP. Callers that need exactly-once semantics must handle it in their own application. Each call produces exactly one audit record regardless of outcome.

#### 4.1.2 Preconditions

- The calling agent exists in Postgres with `state = ACTIVE`.
- The parent domain exists with `state = ACTIVE`.
- The `model_id` appears in the agent's allowlist.
- The caller presents a valid JWT with scope `aihub:invoke`.
- The request is within the agent's RPM, the agent's TPM, and the domain's monthly spend cap (verified as projection before Bedrock is invoked).
- All filter vendor endpoints are reachable.

#### 4.1.3 Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/inference` | Synchronous, non-streaming inference. Primary endpoint. |
| `GET`  | `/v1/models`    | Returns the list of logical model IDs the calling agent is permitted to use. |
| `GET`  | `/v1/health`    | Liveness probe. Returns 200 whenever the process is serving. |
| `GET`  | `/v1/ready`     | Readiness probe. Returns 200 only when all critical downstreams are reachable. |

#### 4.1.4 Request schema: POST /v1/inference

The request body is a JSON object with the fields below. Unknown top-level fields are **rejected** (strict schema); unknown fields inside the `metadata` object are accepted and silently dropped for forward compatibility.

**`model_id`** *(string, required)* — The logical model identifier. Must be a value in the MVP model catalog (section 4.1.10). Unknown values return HTTP 400 `error.code = "invalid_model_id"`. Echoed verbatim in the response and written to the audit record.

**`messages`** *(array, required, minimum 1 item)* — Conversation history in chronological order. Each entry is an object with:
- `role` *(enum: `"user"` | `"assistant"`)*
- `content` *(string OR array of Bedrock Converse content blocks)*

Only text blocks are supported in MVP. Image, document, `tool_use`, and `tool_result` blocks are either rejected with `content_block_not_supported` or passed through as opaque text — see section 1.4.

**`system`** *(string, optional)* — System prompt text. Maximum 32,000 characters. Exceeding the limit returns HTTP 400 `error.code = "invalid_request"` with `error.field = "/system"`.

**`inference_params`** *(object, optional)* — Generation parameters. When present, `max_tokens` is required and must be an integer in `[1, 8192]`. Optional fields: `temperature` (float, `[0.0, 1.0]`), `top_p` (float, `[0.0, 1.0]`), `stop_sequences` (array of up to 4 strings, each up to 256 chars). Unknown fields within `inference_params` are rejected.

**`stream`** *(boolean, optional, default `false`)* — Reserved for v2. When `true` in MVP, the request is rejected with HTTP 400 `error.code = "streaming_not_supported"`.

**`metadata`** *(object, optional)* — Caller-supplied envelope echoed into the audit record but otherwise uninterpreted. Recognized fields: `trace_id` (string, up to 128 chars) and `user_context` (string, up to 256 chars). Additional fields are silently dropped.

#### 4.1.5 Response schema: 200 OK

```json
{
  "request_id": "01JABCDEF...",
  "model_id": "claude-haiku-4-5",
  "completion": "...model output text...",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 482,
    "output_tokens": 1021,
    "total_tokens": 1503
  },
  "latency_ms": {
    "hub_overhead": 412,
    "bedrock": 1840,
    "total": 2252
  }
}
```

**Field semantics:**

- **`request_id`** *(ULID)* — Assigned at Kong ingress; equal to `X-AIHub-Request-Id`; primary key in the audit record.
- **`completion`** *(string)* — Full assembled text. Non-streaming; complete response in a single field.
- **`stop_reason`** *(enum)* — `end_turn` (natural), `max_tokens` (hit maximum), `stop_sequence` (matched caller-supplied stop sequence). Mapped from Bedrock.
- **`usage`** *(object)* — Bedrock's counts; `total_tokens` is their sum. Drives TPM enforcement and cost.
- **`latency_ms`** *(object)* — `hub_overhead` = pre-filter + post-filter + audit-write time; `bedrock` = time in `InvokeModel`; `total` ≈ sum plus small network overhead.

#### 4.1.6 Response headers

| Header | Description | Presence |
|---|---|---|
| `X-AIHub-Request-Id` | Request ULID. | All responses |
| `X-AIHub-Tokens-Used` | `total_tokens` value. | 200 only |
| `X-RateLimit-Limit-RPM` | Configured RPM for the agent. | All |
| `X-RateLimit-Limit-TPM` | Configured TPM for the agent. | All |
| `X-RateLimit-Remaining-TPM` | Best-effort estimate of remaining tokens in current 60s window. | All |
| `Retry-After` | Seconds until retry is allowed. | 429 only |

#### 4.1.7 Error response envelope

All non-200 responses share this JSON envelope. Complete catalog in [Appendix A](#appendix-a--error-code-catalog).

```json
{
  "error": {
    "code": "guardrail_input_block",
    "message": "Prompt was rejected by input filter.",
    "filter": "prompt_injection",
    "field": "/inference_params/max_tokens",
    "request_id": "01JABCDEF..."
  }
}
```

`filter` is present on guardrail errors; `field` is a JSON pointer present on schema errors.

#### 4.1.8 Happy-path narrative

An agent process holds a valid JWT obtained earlier from Ping using client-credentials grant. It constructs a JSON body with `model_id = "claude-haiku-4-5"`, a single-message `messages` array with role `"user"`, no system prompt, and `inference_params` with `max_tokens = 1024` and `temperature = 0.7`. It sends `POST /v1/inference` with the JWT in the Authorization header.

Kong receives the request, validates the JWT against cached Ping JWKS (typical cache age 30–300 seconds), verifies scope `aihub:invoke` is present, enforces the per-agent RPM limit (default 60), injects `X-AIHub-Request-Id` as a freshly-minted ULID, and forwards to AI Hub Core.

Core API deserializes the JSON body and validates against the strict input schema. Validation passes. It extracts the `agent_id` claim from the JWT and performs a single Postgres query that loads the agent record joined with the domain record and the `agent_model_allowlist` entries. The query returns agent with `state = ACTIVE`, domain with `state = ACTIVE`, allowlist containing `"claude-haiku-4-5"`, and the assigned RPM, TPM, and monthly-cap values.

The Entitlement Service runs three checks. It verifies `model_id` is in the allowlist. It estimates input tokens using the model's tokenizer, computes `projected_tokens = current_window_sum + input_estimate + max_tokens`, and rejects if that exceeds TPM. It queries month-to-date spend from Postgres, computes `projected_cost = projected_tokens × price_per_1k / 1000`, and rejects if that exceeds the domain cap. All three pass.

The Input Filter Chain runs. `prompt_injection` returns `ALLOW` in 180ms. `pii_input` returns `ALLOW` in 95ms. `content_policy_input` returns `ALLOW` in 120ms. Total input-filter latency: ~395ms sequential.

The Model Router translates `"claude-haiku-4-5"` to the Bedrock foundation-model ARN, acquires AWS credentials via IAM role assumption (typically cached), and invokes `InvokeModel`. Bedrock returns 200 with completion text and `input_tokens = 482`, `output_tokens = 1021`.

The Output Filter Chain runs on the completion. All three filters return `ALLOW` in combined ~350ms.

The Audit Writer composes the record. It JSON-encodes the full request and response, encrypts the combined payload via envelope encryption (fresh data key, wrapped by per-domain KMS CMK), and uploads to S3 at `s3://<bucket>/audit/v1/domain=<domain_id>/date=2026-04-19/request_id=<ulid>.json.enc` with Object Lock retention set to 13 months. It concurrently indexes the searchable metadata into OpenSearch. Both writes succeed.

The Rate-limit Store is updated: Redis `INCRBY` for the TPM counter with actual 1,503 tokens, overwriting the earlier projection contribution. The Postgres month-to-date spend for the domain is updated by the cost of this call.

Core emits the 200 response. End-to-end ~2,250ms: ~412ms hub overhead and ~1,840ms Bedrock. The caller has the completion.

#### 4.1.9 Exception paths

The exceptions below are specific to FR-1. Authentication exceptions are covered in FR-2, filter exceptions in FR-3 and FR-5, rate-limit and spend exceptions in FR-9, and audit write exceptions in FR-13.

**E1.1 — Malformed JSON body.**
- *Trigger:* Request body is not valid JSON (truncation, bad encoding, wrong content-type).
- *Detection:* JSON parser at Core API entry.
- *Behavior:* Rejected before agent lookup. No Bedrock call.
- *Observable:* HTTP 400 `error.code = "invalid_request"`, `error.message = "Request body is not valid JSON"`.
- *Audit:* No audit record (client error; writing these floods the ledger with noise). Prometheus `aihub_requests_total{outcome="malformed"}` incremented.

**E1.2 — Schema validation failure.**
- *Trigger:* JSON parses but violates input schema (missing `model_id`, empty `messages`, `max_tokens > 8192`, unknown top-level field).
- *Detection:* JSON Schema validator in Core API.
- *Behavior:* Rejected before entitlement. No Bedrock call.
- *Observable:* HTTP 400 `error.code = "invalid_request"`, `error.message` naming the offending field, `error.field` = JSON pointer.
- *Audit:* Audit record `outcome = "error"` to aid debugging. Request payload stored; response payload null.

**E1.3 — Unknown model_id.**
- *Trigger:* `model_id` is a string but not in the MVP catalog.
- *Detection:* Policy Store lookup returns null.
- *Behavior:* Rejected before filters. No Bedrock call.
- *Observable:* HTTP 400 `error.code = "invalid_model_id"`.
- *Audit:* `outcome = "error"`.

**E1.4 — Model not in allowlist.**
- *Trigger:* `model_id` is in the catalog but not in the agent's allowlist.
- *Detection:* Entitlement Service allowlist check.
- *Behavior:* Rejected before filters. No Bedrock call.
- *Observable:* HTTP 403 `error.code = "model_not_allowed"` with `error.message` naming the model and suggesting to contact the Domain Admin.
- *Audit:* `outcome = "rejected_auth"`.

**E1.5 — Streaming requested.**
- *Trigger:* Request body contains `stream: true`.
- *Detection:* Schema validator.
- *Behavior:* Rejected. No Bedrock call.
- *Observable:* HTTP 400 `error.code = "streaming_not_supported"`.
- *Audit:* `outcome = "error"`.

**E1.6 — Unsupported content block.**
- *Trigger:* Request contains image, document, `tool_use`, or `tool_result` content blocks.
- *Detection:* Content block type check.
- *Behavior:* Rejected. No Bedrock call.
- *Observable:* HTTP 400 `error.code = "content_block_not_supported"`.
- *Audit:* `outcome = "error"`.

**E1.7 — Context window exceeded.**
- *Trigger:* Estimated input tokens + `max_tokens` exceeds the model's context window.
- *Detection:* Token estimator before Bedrock invocation.
- *Behavior:* Rejected. No Bedrock call.
- *Observable:* HTTP 400 `error.code = "context_window_exceeded"`, `error.message` giving window size and estimated total.
- *Audit:* `outcome = "error"`; `input_tokens` populated from estimator; `output_tokens` null.

**E1.8 — Suspended agent.**
- *Trigger:* `agent.state != ACTIVE` (could be `SUSPENDED`, `PROVISIONING`, `SUBMITTED`, `ARCHIVED`).
- *Detection:* Agent lookup.
- *Behavior:* Rejected before filters. No Bedrock call.
- *Observable:* HTTP 403 `error.code = "agent_suspended"` (code covers all non-active states; `error.message` is state-specific).
- *Audit:* `outcome = "rejected_auth"`.

**E1.9 — Suspended domain.**
- *Trigger:* `domain.state != ACTIVE`.
- *Detection:* Domain lookup.
- *Behavior:* Rejected. No Bedrock call.
- *Observable:* HTTP 403 `error.code = "domain_suspended"`.
- *Audit:* `outcome = "rejected_auth"`.

**E1.10 — Bedrock ValidationException.**
- *Trigger:* Bedrock rejects the request (e.g., `max_tokens` exceeds the model's per-request maximum).
- *Detection:* Bedrock SDK.
- *Behavior:* Translated to caller. No retry.
- *Observable:* HTTP 400 `error.code = "invalid_request"` with sanitized message.
- *Audit:* `outcome = "error"`, `error_code = "bedrock_validation_exception"`.

**E1.11 — Bedrock ThrottlingException.**
- *Trigger:* Bedrock returns ThrottlingException.
- *Detection:* Bedrock SDK.
- *Behavior:* Model Router retries once after 200ms backoff. If retry also throttles, error is surfaced.
- *Observable:* HTTP 429 `error.code = "bedrock_throttled"`, `Retry-After: 2`.
- *Audit:* Single record `outcome = "error"`; retry attempt noted in metadata.

**E1.12 — Bedrock service unavailable.**
- *Trigger:* Bedrock returns 5xx (`ServiceUnavailableException`, `InternalServerException`, network 5xx).
- *Detection:* Bedrock SDK.
- *Behavior:* Surfaced to caller. No retry (caller's framework is better positioned to retry).
- *Observable:* HTTP 502 `error.code = "bedrock_error"`.
- *Audit:* `outcome = "error"`.

**E1.13 — Bedrock timeout.**
- *Trigger:* Bedrock does not respond within 30 seconds.
- *Detection:* HTTP client timeout.
- *Behavior:* Connection aborted. No retry.
- *Observable:* HTTP 504 `error.code = "bedrock_timeout"`.
- *Audit:* `outcome = "error"`, `latency_ms_bedrock = 30000`.

**E1.14 — Audit write failure.**
- *Trigger:* S3 upload or OpenSearch index write fails after Bedrock returned successfully.
- *Detection:* Audit Writer error handler.
- *Behavior:* Caller does NOT receive the Bedrock response. Hub returns 503. TPM counter and spend counter are still updated (tokens were consumed). Best-effort write to local dead-letter file for reconciliation; caller-visible outcome is 5xx.
- *Observable:* HTTP 503 `error.code = "audit_unavailable"`.
- *Audit:* The thing that failed to write. Dead-letter record retried manually.

**E1.15 — Request body exceeds 1 MB.**
- *Trigger:* Body exceeds Kong's 1 MB max.
- *Detection:* Kong.
- *Behavior:* Kong returns 413 before forwarding. No AI Hub state touched.
- *Observable:* HTTP 413 `error.code = "request_too_large"`.
- *Audit:* No audit record (edge rejection before agent identity was resolved beyond JWT claims). Kong access log with `agent_id`.

#### 4.1.10 MVP model catalog

| Logical `model_id` | Bedrock identifier | Tier | Context window |
|---|---|---|---|
| `claude-haiku-4-5` | `anthropic.claude-haiku-4-5-v1:0` | Standard | 200,000 tokens |
| `claude-sonnet-4-6` | `anthropic.claude-sonnet-4-6-v1:0` | Standard | 200,000 tokens |
| `claude-opus-4-7` | `anthropic.claude-opus-4-7-v1:0` | Restricted | 200,000 tokens |
| `titan-embed-text-v2` | `amazon.titan-embed-text-v2:0` | Standard | 8,192 tokens |

**Tier semantics:**
- **Standard** — Domain Admin may approve on an agent's allowlist without escalation.
- **Restricted** — requires Platform Admin approval in addition to Domain Admin, AND requires the domain to be data-classification tier 3 or 4.

#### 4.1.11 Acceptance criteria

- **AC-1.1** — A valid `POST /v1/inference` with an allowlisted model returns 200 and a body matching the response schema within the end-to-end latency SLA.
- **AC-1.2** — A request with `stream=true` returns HTTP 400 `error.code = "streaming_not_supported"` and writes no Bedrock call.
- **AC-1.3** — A request for a `model_id` not in the agent's allowlist returns 403 `error.code = "model_not_allowed"`.
- **AC-1.4** — A request with an unknown `model_id` returns 400 `error.code = "invalid_model_id"`.
- **AC-1.5** — A request missing required fields returns 400 `error.code = "invalid_request"` with `error.field` naming the offending JSON pointer.
- **AC-1.6** — A request with `max_tokens` outside `[1, 8192]` returns 400 `error.code = "invalid_request"`.
- **AC-1.7** — `request_id` in the body equals the `X-AIHub-Request-Id` header.
- **AC-1.8** — `GET /v1/models` for an Agent Runtime token returns exactly the agent's allowlisted models.
- **AC-1.9** — `GET /v1/health` returns 200 regardless of downstream state.
- **AC-1.10** — `GET /v1/ready` returns 503 when any critical downstream is unreachable.
- **AC-1.11** — Every outcome except E1.1 (malformed JSON) and E1.15 (oversized body) produces exactly one audit record.
- **AC-1.12** — Bedrock ThrottlingException is retried exactly once with 200ms backoff before being surfaced.

---

### 4.2 FR-2 — Edge authentication

#### 4.2.1 Overview

Every API request to AI Hub is authenticated at the Kong edge before reaching any control-plane service. The authentication mechanism is OAuth 2.0 / OIDC with Ping Identity as the sole identity provider. Tokens are JWTs signed with RSA keys rotated by Ping on its own schedule.

The decision to authenticate at the edge is deliberate. If validation were performed at each downstream service, every AI Hub component would need direct connectivity to Ping and a duplicate validation implementation. By validating at Kong, downstream services can trust the claims in the forwarded request as authoritative, which simplifies their code and reduces attack surface.

Two distinct flows produce tokens. Human users — Platform Admins, Domain Admins, Agent Developers, Auditors — obtain tokens through the OAuth 2.0 authorization-code flow with PKCE, typically via a single-page dashboard application. Agent runtime processes obtain tokens through the client-credentials flow using the `client_id` and `client_secret` that were issued to the agent at onboarding (see FR-4).

Tokens are short-lived with a maximum lifetime of 1 hour. AI Hub does not participate in refresh-token flows; human users re-authenticate through the dashboard when their token expires, and agent processes obtain a new token from Ping using client credentials when needed.

#### 4.2.2 Token validation sequence

On every request, Kong performs the following validations in order. The first failure short-circuits and returns the appropriate error.

1. **Header presence.** Kong looks for `Authorization: Bearer <token>`. Missing header → 401 `missing_token`. Malformed header → 401 `malformed_authorization_header`.
2. **JWT decoding.** Kong decodes the JWT header and body. Undecodable → 401 `invalid_token`.
3. **Signature verification.** Kong verifies using the public key identified by `kid` in the JWT header, fetched from Ping's JWKS (cached 300s). If `kid` is unknown, Kong refreshes JWKS once synchronously; if still unknown → 401 `invalid_token`. Signature verification failure → 401 `invalid_token`.
4. **Issuer check.** `iss` claim matches configured Ping issuer URL for the environment. Mismatch → 401 `invalid_issuer`.
5. **Audience check.** `aud` claim equals `"aihub"`. Mismatch → 401 `invalid_audience`.
6. **Expiry check.** `exp` is in the future with ±60 seconds clock-skew tolerance. Expired → 401 `token_expired`.
7. **Not-before check.** `nbf` (if present) is in the past with 60s tolerance. Otherwise → 401 `token_not_yet_valid`.
8. **Scope check.** The scope required for the endpoint is present in the `scope` claim (space-delimited string). Required scope for `/v1/inference` and `/v1/models` is `aihub:invoke`. Mismatch → 403 `insufficient_scope`.
9. **Header propagation.** If all checks pass, Kong extracts claims into downstream headers (`X-Forwarded-Sub`, `X-Forwarded-Agent-Id`, `X-Forwarded-Domain-Id`, `X-Forwarded-Roles`) and proxies to AI Hub Core.

#### 4.2.3 Required JWT claims

| Claim | Required for | Description |
|---|---|---|
| `iss` | All | Ping issuer URL for the environment. |
| `aud` | All | Must equal `"aihub"`. |
| `exp` | All | Unix seconds. Max token lifetime 1 hour from `iat`. |
| `iat` | All | Issued-at timestamp. |
| `sub` | All | Subject: user ID (user flows) or `client_id` (agent flows). |
| `scope` | All | Space-delimited scope string. |
| `roles` | User flows | Array of role strings mapped from Ping groups. |
| `domain_id` | Agent flows | UUID of the domain the agent belongs to. |
| `agent_id` | Agent flows | UUID of the agent. |
| `client_id` | Agent flows | OAuth client ID issued to the agent. |

#### 4.2.4 Scopes

| Scope | Grants access to |
|---|---|
| `aihub:invoke` | `POST /v1/inference`, `GET /v1/models` |
| `aihub:admin` | Platform-wide admin APIs |
| `aihub:domain` | Domain-scoped admin APIs |
| `aihub:audit` | Audit read APIs and extracts |
| `aihub:dashboard` | Dashboard read APIs |

#### 4.2.5 JWKS refresh and failure handling

Ping publishes signing keys at a well-known JWKS endpoint. Kong maintains an in-process cache refreshed every 300 seconds on a background timer. On a cache miss (unknown `kid`), a synchronous refresh is triggered; rate-limited to one refresh per 10 seconds to prevent a thundering herd during key rotation.

Ping key rotation typically happens weekly. During rotation, Ping publishes both old and new keys in JWKS for at least 1 hour, so any reasonable cache interval picks up the new key before old tokens signed with it arrive.

If the JWKS endpoint becomes unreachable, Kong continues to use the last-known-good cache for up to 24 hours (measured from the last successful refresh). If the 24-hour stale threshold is exceeded, Kong fails all token validation with 503 `auth_unavailable` until JWKS is reachable. This protects against Ping outages causing AI Hub to accept arbitrary tokens, while allowing AI Hub to ride through short Ping interruptions without customer impact.

#### 4.2.6 Happy-path narrative

A human Platform Admin loads the dashboard in their browser. The SPA redirects to Ping's authorization endpoint with scopes `aihub:admin aihub:dashboard` and a PKCE challenge. The admin authenticates with corporate SSO and approves the scope grant. Ping redirects back with an authorization code; the SPA exchanges the code for an access token. The token is stored in memory (not `localStorage`) and used for subsequent API calls.

The SPA calls `GET /v1/dashboard/overview` with the token. Kong receives the request, looks up `kid` in cached JWKS (cache age 45 seconds), verifies signature, `iss`, `aud`, `exp` (valid for another 52 minutes), and checks `scope` contains `aihub:dashboard`. All checks pass in under 20ms. Kong extracts `sub` and `roles[]` into `X-Forwarded-Sub` and `X-Forwarded-Roles` headers and proxies to Dashboard API.

Dashboard API further authorizes the request based on roles (Platform Admin is required for this endpoint) and returns aggregate data.

#### 4.2.7 Exception paths

**E2.1 — Missing Authorization header.**
- *Trigger:* Request arrives with no Authorization header.
- *Detection:* Kong JWT plugin.
- *Behavior:* Rejected at edge.
- *Observable:* HTTP 401 `error.code = "missing_token"`.
- *Audit:* No audit record (no agent identity available).

**E2.2 — Malformed header.**
- *Trigger:* Authorization header does not begin with `"Bearer "` or contains unexpected whitespace.
- *Detection:* Kong JWT plugin.
- *Behavior:* Rejected at edge.
- *Observable:* HTTP 401 `error.code = "malformed_authorization_header"`.
- *Audit:* No audit record.

**E2.3 — Invalid signature.**
- *Trigger:* JWT signature does not verify against any current JWKS key.
- *Detection:* Kong JWT plugin; synchronous JWKS refresh attempted once.
- *Behavior:* Rejected after refresh (up to 1 second added latency).
- *Observable:* HTTP 401 `error.code = "invalid_token"`.
- *Audit:* No audit record.

**E2.4 — Wrong issuer.**
- *Trigger:* `iss` does not match configured Ping issuer.
- *Detection:* Kong.
- *Behavior:* Rejected.
- *Observable:* HTTP 401 `error.code = "invalid_issuer"`.
- *Audit:* No audit record.

**E2.5 — Wrong audience.**
- *Trigger:* `aud` claim does not equal `"aihub"` (common cause: token issued for a different service was replayed).
- *Detection:* Kong.
- *Behavior:* Rejected.
- *Observable:* HTTP 401 `error.code = "invalid_audience"`.
- *Audit:* No audit record.

**E2.6 — Expired token.**
- *Trigger:* `exp` claim is in the past beyond the 60-second skew tolerance.
- *Detection:* Kong.
- *Behavior:* Rejected.
- *Observable:* HTTP 401 `error.code = "token_expired"`.
- *Audit:* No audit record.

**E2.7 — Not-yet-valid token.**
- *Trigger:* `nbf` claim is in the future beyond skew tolerance.
- *Detection:* Kong.
- *Behavior:* Rejected.
- *Observable:* HTTP 401 `error.code = "token_not_yet_valid"`.
- *Audit:* No audit record.

**E2.8 — Insufficient scope.**
- *Trigger:* Token valid but lacks the scope required by the endpoint (e.g., Agent Runtime token calling dashboard endpoint).
- *Detection:* Kong scope check.
- *Behavior:* Rejected.
- *Observable:* HTTP 403 `error.code = "insufficient_scope"` with `error.message` listing the required scope.
- *Audit:* Kong access log with `sub` claim for forensics; no AI Hub audit record.

**E2.9 — Ping JWKS temporary unavailability.**
- *Trigger:* JWKS endpoint returns 5xx or is unreachable; cached JWKS < 24 hours old.
- *Detection:* Kong JWKS fetcher.
- *Behavior:* Kong continues to use cached JWKS. No caller-visible impact unless a new `kid` is introduced during the outage (which would fail as E2.3).
- *Observable:* None for tokens signed with cached keys. Operational alert fired for long outage.
- *Audit:* Operational metric `aihub_jwks_stale_seconds` incremented.

**E2.10 — Ping JWKS extended unavailability.**
- *Trigger:* Cached JWKS > 24 hours stale.
- *Detection:* Kong JWKS fetcher.
- *Behavior:* All token validation fails.
- *Observable:* HTTP 503 `error.code = "auth_unavailable"` for all requests.
- *Audit:* No per-request records; system-level incident declared.

#### 4.2.8 Acceptance criteria

- **AC-2.1** — Requests without Authorization header receive 401 within 50ms at Kong.
- **AC-2.2** — Expired tokens receive 401 `error.code = "token_expired"`.
- **AC-2.3** — Unmatched signatures receive 401 `error.code = "invalid_token"` after at most one JWKS refresh.
- **AC-2.4** — A token with scope `aihub:invoke` calls `POST /v1/inference` successfully but receives 403 on admin endpoints.
- **AC-2.5** — Kong uses cached JWKS for at least 300 seconds; JWKS endpoint is not called per-request.
- **AC-2.6** — If Ping JWKS is unreachable but cache < 24 hours old, validation continues normally.
- **AC-2.7** — If Ping JWKS unreachable > 24 hours, all validation fails with 503 `auth_unavailable`.
- **AC-2.8** — Clock-skew up to 60 seconds in either direction does not cause false rejections.

---

### 4.3 FR-3 — Input filter chain

#### 4.3.1 Overview

The input filter chain is AI Hub's first line of defense against misuse of the LLM. It runs three filters sequentially on every inference request after authentication and entitlement have passed but before Bedrock is invoked. Its goal is to block requests that would cause harm (exfiltrating secrets, leaking PII through a prompt, violating content policy) at the cheapest possible point — before any model cost is incurred.

The three filters, in order, are **prompt-injection detection**, **PII scanning**, and **content-policy evaluation**. Each is a pluggable component implementing a common interface; any filter can be replaced without disturbing the others. In MVP, all three are primarily implemented by AWS Bedrock Guardrails, with AWS Comprehend as a fallback for PII detection when Guardrails times out within its budget.

The chain is sequential rather than parallel in MVP. Parallelization is a v1.1 candidate optimization. Sequential execution simplifies reasoning about ordering — when a block occurs, the blocking filter is deterministic and later filters are not invoked, reducing vendor cost. At p95, observed sequential cost is approximately 600–900 ms, which fits inside the hub overhead target.

All input filters are **fail-closed**. If a filter times out or returns an error, the request is rejected with 503 rather than allowed through. An input-filter failure on a prompt that would otherwise be blocked is a security failure; the alternative of fail-open would trade safety for availability. FR-14 records this commitment formally.

#### 4.3.2 Filter interface

Each filter implements the same interface, pluggable and vendor-agnostic:

```python
class Filter(Protocol):
    name: str                        # stable identifier, e.g. "prompt_injection"
    direction: Literal["input", "output"]

    async def run(
        self,
        input: FilterInput,
        deadline_ms: int,
    ) -> FilterVerdict: ...

@dataclass
class FilterInput:
    request_id: str
    domain_id: UUID
    agent_id: UUID
    payload: dict                    # for input: {system?, messages}
                                     # for output: {completion}
    context: dict                    # model_id, etc.

@dataclass
class FilterVerdict:
    filter_name: str
    outcome: Literal["ALLOW", "BLOCK", "ERROR"]
    reason_code: Optional[str] = None          # e.g. "PII_SSN_DETECTED"
    detected_categories: Optional[List[str]] = None
    latency_ms: int = 0
    raw_vendor_response_ref: Optional[str] = None  # S3 key for debugging
```

#### 4.3.3 The three filters

**`prompt_injection`.** The prompt-injection filter scans the concatenation of the system prompt (if any) and all user messages for patterns indicating attempts to subvert the model's intended behavior. Techniques targeted include instruction override ("ignore all previous instructions"), role confusion ("you are now a different assistant"), hidden instruction injection via markup, delimiter confusion, and known jailbreak templates from published adversarial corpuses.

In MVP, this filter is implemented by AWS Bedrock Guardrails' prompt-attack detector. The detector returns one of three signals per scanned text: `NONE` (no attack), `HIGH` (strong confidence), or `MEDIUM` (weaker confidence). AI Hub's MVP policy is to `BLOCK` on `HIGH` and `ALLOW` on `MEDIUM` and `NONE`. Tightening to `MEDIUM`-blocking is a post-MVP tunable.

The filter is called with a 300ms deadline. Timeout or exception → `ERROR` verdict, chain short-circuits, fail-closed (HTTP 503).

**`pii_input`.** The PII input filter scans the same text for PII categories configured in the Policy Store. The MVP category set is:

- US Social Security Number (SSN)
- US Individual Taxpayer Identification Number (ITIN)
- Credit card primary account number (any major scheme)
- US passport number
- US driver's license number
- US bank account + routing number pair
- Phone number (US formats)
- IPv4 / IPv6 address *(warn-only)*
- Email address *(warn-only)*
- Personal-name + date-of-birth pairing
- US physical street address

"Warn-only" categories generate an audit annotation but do not block — legitimate prompts frequently contain emails and IP addresses. This configuration is versioned in the Policy Store and is changeable by Platform Admin with documented change-management.

Primary implementation is Bedrock Guardrails' sensitive-information filter. If Guardrails exceeds a 150ms soft timeout, a fallback call to AWS Comprehend `DetectPiiEntities` is made with the remaining budget. Results are merged (union of detected categories). Both missing the 300ms hard deadline → `ERROR`, chain short-circuits.

Redaction as a `BLOCK` alternative is not in MVP. A future `REDACT` option would replace detected PII with placeholders and forward the redacted prompt to Bedrock; tracked in v2.

**`content_policy_input`.** The content-policy filter evaluates the request against organization-wide denied topics and use cases: generating legal advice as if from a lawyer, producing medical diagnoses as if from a clinician, generating financial-advice content with specific price/instrument recommendations, generating content about individuals by name without consent, and a configurable deny list maintained by the AI Center of Excellence.

Implementation: a Bedrock Guardrail resource configured with denied topics and content filters (violence, hate, sexual, insults, misconduct, prompt-attack). Returns `BLOCK` on any trigger with `HIGH` confidence.

Same 300ms deadline, fail-closed.

#### 4.3.4 Chain orchestration

The chain runs filters in the fixed order `prompt_injection` → `pii_input` → `content_policy_input`. The orchestrator invokes each filter with a 300ms per-filter deadline. On the first `BLOCK` or `ERROR`, short-circuit — later filters not invoked. All verdicts (including those that ran before short-circuit) are recorded in the audit record's `filter_verdicts` array.

Per-filter latency is logged to the `aihub_filter_duration_ms` histogram (labeled by filter name and outcome). Cumulative input-filter latency is a distinct OpenTelemetry span.

#### 4.3.5 Happy-path narrative

A user prompt reaches the Input Filter Chain after entitlement has passed. The orchestrator invokes `prompt_injection` first. The filter constructs a Bedrock Guardrails request with the concatenated text and calls the Guardrails API. Guardrails responds in 180ms with `NONE`. Verdict is `ALLOW`, `latency_ms = 180`.

The orchestrator invokes `pii_input` next. The filter calls Guardrails' sensitive-information endpoint, which responds in 120ms with an empty detected-categories set. Verdict `ALLOW`, `latency_ms = 120`.

The orchestrator invokes `content_policy_input` last. This filter calls the configured Guardrail resource, which applies both the denied-topic list and the content filters. Response is `NONE` in 150ms. Verdict `ALLOW`.

Total input-filter time: ~450ms. The orchestrator returns `ALLOW` to Core API, which proceeds to Bedrock invocation. The three verdicts are carried forward in memory and written to the audit record at the end of the request.

#### 4.3.6 Exception paths

**E3.1 — `prompt_injection` BLOCK.**
- *Trigger:* Filter returns `BLOCK` (Guardrails reports HIGH-confidence prompt attack).
- *Detection:* Orchestrator.
- *Behavior:* Chain short-circuits. `pii_input` and `content_policy_input` NOT invoked. Bedrock NOT invoked. No TPM consumption; no spend.
- *Observable:* HTTP 422 `error.code = "guardrail_input_block"`, `error.filter = "prompt_injection"`, `error.message = "Prompt rejected by input filter."`
- *Audit:* `outcome = "rejected_input"`; `filter_verdicts` contains the single BLOCK with its `reason_code`.

**E3.2 — `pii_input` BLOCK.**
- *Trigger:* Filter returns `BLOCK` (detected one or more PII categories not marked warn-only).
- *Detection:* Orchestrator.
- *Behavior:* Chain short-circuits. `content_policy_input` NOT invoked. Bedrock NOT invoked.
- *Observable:* HTTP 422 `error.code = "guardrail_input_block"`, `error.filter = "pii_input"`, `error.message` lists the detected categories.
- *Audit:* `outcome = "rejected_input"`; `filter_verdicts` contains ALLOW from `prompt_injection` and BLOCK from `pii_input`.

**E3.3 — `content_policy_input` BLOCK.**
- *Trigger:* Filter returns `BLOCK`.
- *Detection:* Orchestrator.
- *Behavior:* Chain short-circuits. Bedrock NOT invoked.
- *Observable:* HTTP 422 `error.code = "guardrail_input_block"`, `error.filter = "content_policy_input"`.
- *Audit:* `outcome = "rejected_input"`; `filter_verdicts` contains all three verdicts (ALLOW/ALLOW/BLOCK).

**E3.4 — Filter timeout.**
- *Trigger:* Any filter does not return within its 300ms deadline.
- *Detection:* `asyncio.wait_for` in orchestrator.
- *Behavior:* Task cancelled. Verdict `ERROR`. Chain short-circuits. Bedrock NOT invoked. Fail-closed.
- *Observable:* HTTP 503 `error.code = "guardrail_timeout"`, `error.filter` = name of filter that timed out.
- *Audit:* `outcome = "error"`; `filter_verdicts` contains the ERROR verdict and any prior ALLOWs.

**E3.5 — Filter vendor error.**
- *Trigger:* Filter raises non-timeout exception (SDK error, vendor 5xx, credential failure).
- *Detection:* Try/except in filter implementation.
- *Behavior:* Verdict `ERROR`. Chain short-circuits. Fail-closed.
- *Observable:* HTTP 503 `error.code = "guardrail_error"`, `error.filter = name`.
- *Audit:* `outcome = "error"`; `filter_verdicts` contains ERROR with `raw_vendor_response_ref` pointing to S3 key of stored exception trace.

#### 4.3.7 Side effects of a BLOCK

When the input filter chain blocks, the following state changes occur:

- **No Bedrock call** → no tokens consumed, no cost incurred.
- **TPM counter not incremented** (no tokens actually used).
- **RPM counter was already incremented at Kong** — consistent with charging RPM for the full attempt including failures.
- **Month-to-date spend not updated**.
- **Audit record written synchronously** with full request payload (encrypted) and null response.
- **Prometheus counter** `aihub_guardrail_blocks_total{filter, direction="input"}` incremented.

#### 4.3.8 Acceptance criteria

- **AC-3.1** — A request containing a known prompt-injection test string returns 422 `error.code = "guardrail_input_block"`, `error.filter = "prompt_injection"`.
- **AC-3.2** — A request containing a test SSN returns 422 `error.filter = "pii_input"`.
- **AC-3.3** — A request violating content policy returns 422 `error.filter = "content_policy_input"`.
- **AC-3.4** — On BLOCK, no Bedrock call is made (verified via zero Bedrock invocations on test harness).
- **AC-3.5** — On BLOCK, the audit record contains exactly the verdicts from filters that were invoked, in order.
- **AC-3.6** — A filter exceeding its 300ms deadline causes 503 `error.code = "guardrail_timeout"`.
- **AC-3.7** — A filter raising a vendor error causes 503 `error.code = "guardrail_error"`.
- **AC-3.8** — Domain Admin can view BLOCK events for their domain's agents in the domain dashboard within 15 seconds.
- **AC-3.9** — Guardrail regression suite achieves ≥95% detection on the known-violation corpus and ≤5% false positive on the benign corpus.

---

### 4.4 FR-4 — Machine-to-machine authentication

#### 4.4.1 Overview

Agent Runtime is a machine identity: the running process of an agent that invokes `POST /v1/inference`. Machine identity must be strong enough that a compromised agent credential is containable and revocable quickly, short-lived enough that theft of a token is of limited duration, and operationally simple enough that agent developers do not invent their own work-arounds.

AI Hub uses OAuth 2.0 client-credentials grant, implemented by Ping Identity. Each registered agent has a unique Ping OAuth client with its own `client_id` and `client_secret`. The agent process uses these at runtime to obtain an access token from Ping, then uses the access token in the Authorization header for AI Hub calls. Ping is the system of record for agent secrets; AI Hub never stores the `client_secret`.

Secrets are delivered exactly once at agent onboarding and are not retrievable afterward. If a secret is lost, the only path is rotation. Rotation is self-service via the domain dashboard and includes a 1-hour grace period during which both old and new secrets are valid, so a rolling deployment of an agent has time to pick up the new secret without downtime.

#### 4.4.2 Credential lifecycle

**Issuance.** At agent onboarding (FR-8), after the agent enters the `PROVISIONING` state, the Registration Service calls Ping's admin API to register a new OAuth client. The client is configured with `client_credentials` grant type enabled, scope `aihub:invoke` allowed, and two custom claims: `domain_id` and `agent_id`, populated with the agent's partition keys. Ping returns the `client_id` and a freshly-generated `client_secret`. The Registration Service stores `client_id` in the agent record in Postgres and packages the `client_secret` into the starter-kit ZIP for single-download delivery. The Registration Service never persists the `client_secret`.

**Token acquisition.** The agent process obtains a token by posting to Ping's token endpoint:

```
POST https://<ping-host>/as/token.oauth2
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&
client_id=<agent_client_id>&
client_secret=<agent_client_secret>&
scope=aihub:invoke

→ HTTP 200
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "scope": "aihub:invoke"
}
```

**Rotation.** A Domain Admin or the agent's Developer initiates rotation via `POST /v1/agents/{id}/rotate-secret` on the AI Hub dashboard or API. The Registration Service calls Ping to mint a new `client_secret` for the client while preserving the `client_id`. Ping marks the old secret as deprecated — valid for a 1-hour grace period — and returns the new secret. The new secret is shown to the initiator once. After the grace period, Ping invalidates the old secret. This gives the agent operator time to roll their deployment without downtime: new instances use the new secret; existing instances holding already-issued access tokens continue to work until their 1-hour token lifetime expires.

**Revocation.** Revocation is an immediate, irreversible disablement of an agent's credential. It is invoked via `POST /v1/agents/{id}/revoke` by a Domain Admin or Platform Admin. The Registration Service calls Ping to disable the OAuth client. Ping stops issuing new tokens for that client immediately. Tokens that have already been issued remain valid for up to 1 hour (their natural lifetime); if faster cutoff is required for an active incident, AI Hub can be configured to maintain a revocation deny-list checked at Kong — not enabled by default in MVP to avoid the latency cost on every request, but can be switched on per incident.

#### 4.4.3 Happy-path narrative

At deployment time, an agent's container image is started with the `client_id` and `client_secret` supplied via environment variables sourced from the caller's own AWS Secrets Manager (not AI Hub's). On the first request, the agent's AI Hub client library detects no cached access token, posts to Ping's token endpoint with client-credentials grant, and receives an access token with `expires_in = 3600`. The library caches the token in memory and schedules a refresh 60 seconds before expiry. All subsequent inference requests within the hour use the cached token. A few minutes before expiry, the library fetches a fresh token proactively. The agent never experiences a visible 401 due to expiry.

#### 4.4.4 Exception paths

**E4.1 — Incorrect client_secret.**
- *Trigger:* Agent presents wrong `client_secret` to Ping.
- *Detection:* Ping.
- *Behavior:* Ping returns 401 `invalid_client`. No AI Hub call is made.
- *Observable:* Agent's own library surfaces an error to its application code.
- *Audit:* No AI Hub audit record. Ping's audit trail records the failed attempt.

**E4.2 — Rotation with in-flight old secret use.**
- *Trigger:* Rotation just occurred; an agent instance still using the old secret requests a new token.
- *Detection:* Ping.
- *Behavior:* Within the 1-hour grace period, Ping honors the old secret. After grace, Ping rejects it.
- *Observable:* Within grace, call succeeds normally. After grace, token fetch fails (like E4.1).
- *Audit:* No AI Hub record. Ping records both old-secret use and the rotation event.

**E4.3 — Revoked client attempts token fetch.**
- *Trigger:* Agent's client has been revoked.
- *Detection:* Ping.
- *Behavior:* Ping refuses to issue a new token.
- *Observable:* Token fetch fails with 401. Any previously-issued access token continues to be accepted by Kong until its expiry (up to 1 hour).
- *Audit:* Revocation event logged in `agent_events`.

**E4.4 — Token for suspended agent.**
- *Trigger:* Agent has a valid token (not yet expired) but agent record moved to `SUSPENDED`.
- *Detection:* Kong passes token validation; Core API checks agent state and rejects.
- *Behavior:* Rejected by Core API, not Kong. Token itself is technically valid.
- *Observable:* HTTP 403 `error.code = "agent_suspended"`.
- *Audit:* Audit record `outcome = "rejected_auth"`.

**E4.5 — Ping unavailable during rotation.**
- *Trigger:* Ping admin API fails during `POST /v1/agents/{id}/rotate-secret`.
- *Detection:* Registration Service.
- *Behavior:* Rotation fails. The existing secret remains valid. Dashboard displays error. No partial state — rotation completes or it doesn't.
- *Observable:* HTTP 503 `error.code = "idp_unavailable"`.
- *Audit:* Operational alert fired.

#### 4.4.5 Acceptance criteria

- **AC-4.1** — Successful agent onboarding returns a `client_id` and `client_secret` exactly once; the starter-kit signed URL is one-time.
- **AC-4.2** — The `client_secret` is not visible in any subsequent API response or dashboard view.
- **AC-4.3** — An agent can obtain a valid JWT from Ping using its `client_id` and `client_secret` via client-credentials grant.
- **AC-4.4** — The JWT contains `domain_id` and `agent_id` claims matching the agent's identity in AI Hub.
- **AC-4.5** — `POST /v1/agents/{id}/rotate-secret` returns a new `client_secret` and keeps the old valid for exactly 1 hour.
- **AC-4.6** — `POST /v1/agents/{id}/revoke` causes Ping to refuse further token issuance immediately; existing valid tokens continue to work until natural expiry.
- **AC-4.7** — Agent tokens cannot be used on admin endpoints (scope mismatch → 403).
- **AC-4.8** — A revocation event is logged in `agent_events` with actor and timestamp.

---

### 4.5 FR-5 — Output filter chain

#### 4.5.1 Overview

The output filter chain is applied to every successful Bedrock response before it is returned to the caller. Its goal is to prevent the model from surfacing content that violates organizational policy or contains PII that should never leave AI Hub. Its structure mirrors the input filter chain — sequential execution of three filters, 300ms per-filter deadline, fail-closed posture — but there is a critical difference in economic effect: by the time the output chain runs, Bedrock has already consumed tokens and incurred cost. A BLOCK on output means the caller paid (via the domain's spend counter) for a response they never received. This is deliberate. The alternative — returning potentially harmful content and telling Compliance about it later — is not acceptable.

The three output filters, in order, are **`pii_output`**, **`harmful_content`**, and **`policy_compliance_output`**. All three are primarily implemented by Bedrock Guardrails with the same filter interface as the input chain.

#### 4.5.2 The three filters

**`pii_output`.** Scans the model's completion for the same PII categories as `pii_input`. The reason for doing both is defense-in-depth: even if the input prompt contained no PII, a model might hallucinate or extract PII from training data. Same Bedrock Guardrails / Comprehend fallback.

**`harmful_content`.** Evaluates the completion against Bedrock Guardrails' content filters tuned for violence, self-harm, sexual, hate, insults, and misconduct categories. Each category has a `HIGH` threshold that triggers BLOCK. Thresholds are stored in the Policy Store and tunable by Platform Admin.

**`policy_compliance_output`.** Evaluates the completion against the output-side denied-topics list, distinct from the input-side list. Examples: making specific financial recommendations with price targets, making medical diagnoses with claimed certainty, making definitive legal claims. The list is maintained by the AI Center of Excellence.

#### 4.5.3 Happy-path narrative

Bedrock has returned 200 to Core API. The completion text is extracted. The orchestrator invokes `pii_output` with 300ms deadline; returns `ALLOW` in 110ms. Invokes `harmful_content`; returns `ALLOW` in 140ms. Invokes `policy_compliance_output`; returns `ALLOW` in 100ms. Total output-filter time ~350ms. The Audit Writer is then invoked.

#### 4.5.4 Exception paths

**E5.1 — `pii_output` BLOCK.**
- *Trigger:* Filter detects PII in completion.
- *Detection:* Orchestrator.
- *Behavior:* Chain short-circuits; later filters not invoked. Completion NOT returned to caller.
- *Observable:* HTTP 502 `error.code = "guardrail_output_block"`, `error.filter = "pii_output"`.
- *Audit:* `outcome = "rejected_output"`; `filter_verdicts` contains BLOCK; full response payload stored encrypted in S3.

**E5.2 — `harmful_content` BLOCK.**
- *Trigger:* Filter detects disallowed content.
- *Detection:* Orchestrator.
- *Behavior:* Chain short-circuits; `policy_compliance_output` not invoked. Completion NOT returned.
- *Observable:* HTTP 502 `error.code = "guardrail_output_block"`, `error.filter = "harmful_content"`.
- *Audit:* `outcome = "rejected_output"`; `filter_verdicts` contains ALLOW (`pii_output`) + BLOCK (`harmful_content`).

**E5.3 — `policy_compliance_output` BLOCK.**
- *Trigger:* Filter detects a disallowed topic.
- *Detection:* Orchestrator.
- *Behavior:* Completion NOT returned.
- *Observable:* HTTP 502 `error.code = "guardrail_output_block"`, `error.filter = "policy_compliance_output"`.
- *Audit:* `outcome = "rejected_output"`; `filter_verdicts` contains all three.

**E5.4 — Filter timeout.**
- *Trigger:* Output filter exceeds 300ms deadline.
- *Detection:* `asyncio.wait_for`.
- *Behavior:* Verdict `ERROR`, chain short-circuits, fail-closed. Completion NOT returned.
- *Observable:* HTTP 503 `error.code = "guardrail_timeout"`, `error.filter = name`.
- *Audit:* `outcome = "error"`; response payload is stored (it exists).

**E5.5 — Filter vendor error.**
- *Trigger:* Output filter raises non-timeout exception.
- *Detection:* Try/except.
- *Behavior:* Verdict `ERROR`, chain short-circuits, fail-closed.
- *Observable:* HTTP 503 `error.code = "guardrail_error"`, `error.filter = name`.
- *Audit:* `outcome = "error"`; vendor exception trace at `raw_vendor_response_ref`.

#### 4.5.5 Side effects of an output BLOCK

Unlike input BLOCK, output BLOCK occurs **after** Bedrock has consumed tokens:

- **TPM counter IS updated** with actual consumed tokens.
- **Domain month-to-date spend IS incremented** by the cost of this call.
- **Caller receives no completion** — HTTP 502.

This produces a situation where a caller can be charged for a call whose result they did not receive. This is intentional — the rejection of harmful output is exactly the value AI Hub is providing, and consumers should understand that blocked output is not refunded. This is documented in the starter kit and in the dashboard messaging. If a consistent high-block-rate is observed for a specific agent, it is a signal of prompt-design issues the agent developer needs to address; the dashboard surfaces this ratio prominently.

#### 4.5.6 Acceptance criteria

- **AC-5.1** — A response containing a known PII pattern is blocked with 502 `error.filter = "pii_output"`.
- **AC-5.2** — A response containing known harmful content is blocked with 502 `error.filter = "harmful_content"`.
- **AC-5.3** — A blocked output is stored in the audit ledger with the full encrypted response body.
- **AC-5.4** — A blocked output increments the TPM counter and the domain spend counter.
- **AC-5.5** — Output filters run on the full assembled completion (streaming not supported in MVP).
- **AC-5.6** — An output-filter timeout causes 503 `error.code = "guardrail_timeout"` and the completion is not returned.

---

### 4.6 FR-6 — Role-based access control

#### 4.6.1 Overview

RBAC in AI Hub is enforced at two layers. Kong enforces coarse scope-level checks at the edge for each route. AI Hub control-plane services enforce fine-grained, contextual checks that depend on data relationships — for example, "this Domain Admin can act on this agent because the agent belongs to a domain where the Domain Admin is listed as an owner."

The five roles are defined in section 3. Each role maps to a set of OAuth scopes at Ping; the scopes appear in the JWT's `scope` claim. Context-dependent authorization is performed in the control plane by joining the authenticated subject's claims against the Postgres data.

All failed authorization attempts produce an audit record (except those rejected at Kong for purely anonymous reasons — no token, wrong audience — where no AI Hub agent identity exists). This gives Auditors visibility into attempted privilege escalation.

#### 4.6.2 Enforcement points

**Kong** performs scope enforcement. For each route it knows the required scope and rejects requests whose token does not contain it. This is the only RBAC Kong performs; it does not look at the `roles[]` claim.

**AI Hub Core API** performs additional role and context checks. On any admin or domain-scoped API, Core API extracts the `roles[]` claim (human) or the `agent_id`/`domain_id` claims (machine) and verifies that the caller's role grants the requested operation on the requested resource. For operations that are domain-scoped, Core API verifies the caller's domain matches the target domain — a Domain Admin of domain A receives 403 on attempts to act on domain B, even though they have the `aihub:domain` scope.

**Dashboard API** performs row-level partition filtering on all queries. When a Domain Admin queries any endpoint, the Dashboard API adds a `domain_id = <caller's domain>` clause to every underlying SQL or OpenSearch query. Implemented as middleware that cannot be bypassed from route handlers.

**Audit read APIs** cross-check the Auditor's scope configuration against the queried partition. The Auditor role has a separate `auditor_scope` field in the `users` table that lists the `domain_ids` the auditor may access (or a wildcard); the audit read middleware enforces this.

#### 4.6.3 Role-to-scope mapping

| Role | OAuth scopes |
|---|---|
| Platform Admin | `aihub:admin aihub:domain aihub:audit aihub:dashboard` |
| Domain Admin | `aihub:domain aihub:dashboard` |
| Agent Developer | `aihub:dashboard` |
| Agent Runtime | `aihub:invoke` |
| Auditor | `aihub:audit aihub:dashboard` |

#### 4.6.4 Happy-path narrative

A Domain Admin logs into the dashboard for domain `fraud-analytics`. The SPA obtains a token with scopes `aihub:domain aihub:dashboard` and a `roles[]` claim containing `"domain_admin"`. The Domain Admin clicks on Agents, and the SPA calls `GET /v1/domains/<their_domain_id>/agents`.

Kong validates the token, sees scope `aihub:dashboard`, and forwards the request. Dashboard API receives the request, extracts the `sub` and `roles` claims, and extracts the path parameter `domain_id`. The middleware loads the user's record from Postgres and confirms they are a primary or secondary owner of the specified `domain_id`. Authorization passes. The route handler executes a query filtered by `domain_id`, returning the list of agents in that domain.

If the same Domain Admin attempted `GET /v1/domains/<other_domain_id>/agents`, the middleware would detect the mismatch between the path parameter and the caller's owned domains, return 403 `out_of_scope_partition`, and write an audit record against the caller's own domain partition noting the cross-partition attempt.

#### 4.6.5 Exception paths

**E6.1 — Insufficient scope.**
- *Trigger:* Token lacks the scope required by the endpoint.
- *Detection:* Kong.
- *Behavior:* Rejected at edge.
- *Observable:* HTTP 403 `error.code = "insufficient_scope"`.
- *Audit:* Kong access log; no AI Hub audit record.

**E6.2 — Cross-partition access attempt.**
- *Trigger:* Domain Admin of domain A tries to read or modify a resource in domain B.
- *Detection:* Dashboard API middleware or Core API role check.
- *Behavior:* Rejected in the control plane.
- *Observable:* HTTP 403 `error.code = "out_of_scope_partition"`.
- *Audit:* Audit record written against the caller's domain partition with `outcome = "rejected_auth"` and a note identifying the cross-partition attempt.

**E6.3 — Role removed during session.**
- *Trigger:* User's Ping group membership was revoked after access token was issued.
- *Detection:* Ping re-issue; tokens already issued retain the old claims.
- *Behavior:* The current token continues to work until its 1-hour expiry. On next refresh, the new claims take effect.
- *Observable:* Within 1 hour the user loses access. For emergency revocation, Platform Admin can force session termination at Ping.
- *Audit:* Continued actions within the 1-hour window are audited under the old role.

**E6.4 — Agent Runtime token on admin endpoint.**
- *Trigger:* Agent Runtime token used to call a dashboard or admin endpoint.
- *Detection:* Kong scope check (agent tokens have only `aihub:invoke`).
- *Behavior:* Rejected at edge.
- *Observable:* HTTP 403 `error.code = "insufficient_scope"`.
- *Audit:* Kong access log.

**E6.5 — Auditor querying out of scope.**
- *Trigger:* Auditor scoped to domain A attempts audit query on domain B.
- *Detection:* Audit read middleware.
- *Behavior:* Rejected.
- *Observable:* HTTP 403 `error.code = "out_of_scope_partition"`.
- *Audit:* The attempt is itself audited (auditors are auditable).

#### 4.6.6 Acceptance criteria

- **AC-6.1** — A Domain Admin for domain A receives 403 on `GET /v1/domains/B/agents`.
- **AC-6.2** — An Agent Developer sees only agents they own or co-own in the domain dashboard, even though the backing API query is the same as a Domain Admin's.
- **AC-6.3** — An Auditor scoped to domain A cannot query audit records for domain B (403).
- **AC-6.4** — An Agent Runtime token cannot call any admin or dashboard endpoint.
- **AC-6.5** — A Platform Admin can read and act across all domains.
- **AC-6.6** — All cross-partition attempts produce an audit record against the caller's partition.

---

### 4.7 FR-7 — Domain onboarding

#### 4.7.1 Overview

Domain onboarding is the process by which a business unit becomes a first-class tenant of AI Hub. The workflow is self-service initiation with human-in-the-loop approval: a prospective owner submits a registration form; the Platform Engineering team reviews and approves; AI Hub automates the provisioning. MVP does not offer fully-automated self-service because the first phase of AI Hub rollout intentionally keeps Platform Engineering in the loop to catch misconfigurations and misuse early. The approval workflow is designed to take no longer than one business day in normal operation.

#### 4.7.2 State machine

```
  [none]
    │  POST /v1/domains  (submit)
    ▼
  [SUBMITTED]
    │                                   reject
    │  POST /approve                    ▲
    ▼                                   │
  [PROVISIONING] ─────────────────▶ [REJECTED]  (terminal)
    │
    │  provisioning actions succeed (automated)
    ▼
  [ACTIVE]  ◀──── POST /resume ──── [SUSPENDED]
    │                                   ▲
    │  POST /suspend                    │
    └───────────────────────────────────┘
    │
    │  POST /archive (requires 0 active agents)
    ▼
  [ARCHIVED]  (terminal)
```

#### 4.7.3 Registration form fields

| Field | Type | Required | Validation |
|---|---|---|---|
| `domain_name` | string | Y | 3..64 chars, lowercase alphanumeric and hyphens, globally unique. Regex `^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$`. |
| `business_unit` | string | Y | Free text, 1..128 chars. |
| `primary_owner_email` | string | Y | Corporate email, must resolve to an active Ping user. |
| `secondary_owner_email` | string | Y | Distinct from primary; must resolve in Ping. |
| `cost_center` | string | Y | Regex `^[0-9]{8}$`. |
| `data_classification_tier` | int | Y | 1..4 per corporate data classification policy. |
| `intended_use_summary` | text | Y | 50..2000 chars; captured in the audit ledger for the submission. |
| `expected_agent_count` | int | N | 0..100. Informational. |
| `expected_monthly_requests` | int | N | 0..10,000,000. Informational. |

#### 4.7.4 Provisioning actions (automated)

When a Platform Admin approves a submission, the Registration Service transitions the record to `PROVISIONING` and runs provisioning actions in the following order. Each action is **idempotent** so that on partial failure a retry resumes from the failed step without duplicating prior work. Any action that cannot complete in three attempts causes the domain to remain in `PROVISIONING` until a Platform Admin investigates.

1. **Create per-domain KMS key.** Key policy generated from template: root Platform Admin role granted key administration; primary and secondary owners granted decrypt on payload objects tagged for this domain; AI Hub service role granted encrypt to write audit payloads. Key ARN saved to `domains.kms_key_arn`.
2. **Provision S3 prefix.** Create `s3://aihub-audit-payloads-<env>/audit/v1/domain=<domain_id>/` and apply Object Lock Compliance mode with configured default retention.
3. **Create OpenSearch index alias.** `audit-<domain_id>-<yyyy-mm>` for current month with canonical index template.
4. **Assign Domain Admin role.** Add primary and secondary owner users to the `Domain-Admin-<domain_id>` Ping group (grants `aihub:domain` and `aihub:dashboard` scopes scoped to the domain).
5. **Set default monthly spend cap.** Based on `data_classification_tier` (see FR-9).
6. **Set default RPM and TPM ceilings.** These are the maximum values the Domain Admin can assign to any agent.
7. **Emit welcome email** to the primary owner with dashboard URL and agent-onboarding guide.

When all seven actions succeed, the domain transitions to `ACTIVE` and is visible on the platform dashboard.

#### 4.7.5 Happy-path narrative

A business-unit lead navigates to the AI Hub public URL and clicks "Register a new domain". They authenticate via SSO to Ping (any corporate user can submit; there is no special scope needed to submit). They fill out the form with `domain_name = "fraud-analytics"`, `business_unit = "Risk & Compliance"`, primary and secondary owner emails, `cost_center = "10024589"`, `data_classification_tier = 3` (Confidential), and a 200-character `intended_use_summary`. They submit.

The Registration Service validates every field. Validation passes. A row is inserted into `domains` with `state = SUBMITTED`. A row is inserted into `domain_events` capturing the submission. An email is sent to the platform-engineering distribution list with a deep link to the pending-approval UI and all submitted fields. The submitter is shown a confirmation screen with their new `domain_id` and a status of "Submitted — pending Platform Engineering review."

A Platform Admin receives the email ~30 seconds later. They open the approval UI, review the fields (confirming cost center is valid and data classification tier is reasonable for the described use case), and click Approve. The Registration Service transitions the record to `PROVISIONING` and enqueues the provisioning job.

The provisioning job runs the seven actions. Each takes a few seconds. KMS key creation typically under 5 seconds; S3 prefix and Object Lock configuration under 2 seconds; OpenSearch index alias under 1 second; Ping group assignment under 5 seconds; policy store updates under 1 second; email sending immediate.

Total provisioning time: under 30 seconds. The record transitions to `ACTIVE`. The primary owner receives the welcome email and, on logging into the dashboard, sees the new domain ready for agent registration.

#### 4.7.6 Exception paths

**E7.1 — Duplicate domain name.**
- *Trigger:* Submission uses a `domain_name` that already exists.
- *Detection:* Postgres UNIQUE constraint on `domains.name`.
- *Behavior:* Submission fails.
- *Observable:* HTTP 409 `error.code = "domain_name_conflict"`.
- *Audit:* No domain record created; attempt logged in application logs.

**E7.2 — Invalid cost center.**
- *Trigger:* `cost_center` doesn't match 8-digit regex.
- *Detection:* Form validator.
- *Behavior:* Rejected.
- *Observable:* HTTP 400 `error.code = "invalid_request"`, `error.field = "cost_center"`.
- *Audit:* No domain record.

**E7.3 — Primary equals secondary owner.**
- *Trigger:* `primary_owner_email` equals `secondary_owner_email`.
- *Detection:* Form validator.
- *Behavior:* Rejected.
- *Observable:* HTTP 400 `error.code = "invalid_request"`, `error.field = "secondary_owner_email"`.
- *Audit:* None.

**E7.4 — Owner not in Ping directory.**
- *Trigger:* Primary or secondary owner email does not resolve to an active Ping user.
- *Detection:* Ping lookup in Registration Service.
- *Behavior:* Rejected.
- *Observable:* HTTP 400 `error.code = "user_not_found"`, `error.field` identifying which email.
- *Audit:* None.

**E7.5 — Rejection by Platform Admin.**
- *Trigger:* Platform Admin clicks Reject on a `SUBMITTED` domain.
- *Detection:* Explicit action in the approval UI.
- *Behavior:* Record transitions to `REJECTED` (terminal). A reason field is required and stored. Email sent to submitter.
- *Observable:* Submitter sees updated status in dashboard. May submit new application with different name.
- *Audit:* `domain_events` row with `event_type = 'rejected'` and actor user id.

**E7.6 — Provisioning partial failure.**
- *Trigger:* One of the seven provisioning actions fails (transient AWS API failure, Ping API timeout).
- *Detection:* Provisioning job.
- *Behavior:* Action retried up to 3 times with exponential backoff. If all fail, domain remains in `PROVISIONING` and alert fires to Platform Engineering. Previously completed actions are **not rolled back** — most have no rollback cost, and partial completion can be resumed.
- *Observable:* Submitter sees domain stuck in `PROVISIONING`; operational incident declared.
- *Audit:* `domain_events` row for each action attempt and the final alert.

**E7.7 — Suspension.**
- *Trigger:* Platform Admin calls `POST /v1/domains/{id}/suspend`, typically due to incident or contract issue.
- *Detection:* Explicit action.
- *Behavior:* Domain transitions to `SUSPENDED`. In Ping, the domain's Domain-Admin group is marked inactive; all domain's agent OAuth clients disabled. New tokens cannot be minted. In-flight tokens continue to work until natural expiry (up to 1 hour). Subsequent `/v1/inference` calls fail with 403 `agent_suspended` or `domain_suspended`.
- *Observable:* Dashboard displays domain as Suspended; all agents as unavailable.
- *Audit:* `domain_events` row with `event_type = 'suspended'` and reason.

**E7.8 — Archive with active agents.**
- *Trigger:* Platform Admin tries to archive a domain with agents in `ACTIVE` state.
- *Detection:* Registration Service pre-check.
- *Behavior:* Rejected.
- *Observable:* HTTP 409 `error.code = "domain_has_active_agents"`, `error.message` listing the blocking agents.
- *Audit:* None (no state change).

#### 4.7.7 Acceptance criteria

- **AC-7.1** — Valid submission creates a record with `state = SUBMITTED` and sends a notification email to Platform Engineering within 60 seconds.
- **AC-7.2** — Duplicate `domain_name` returns 409.
- **AC-7.3** — Invalid `cost_center` returns 400 with `error.field = "cost_center"`.
- **AC-7.4** — Owner emails that do not resolve in Ping return 400 `error.code = "user_not_found"`.
- **AC-7.5** — Platform Admin approval transitions record to `PROVISIONING` within 10 seconds and to `ACTIVE` within 60 seconds in normal conditions.
- **AC-7.6** — Provisioning is idempotent; a retry after partial success does not create duplicate KMS keys or duplicate Ping group entries.
- **AC-7.7** — Primary owner receives the welcome email within 2 minutes of the `ACTIVE` transition.
- **AC-7.8** — Suspension disables all domain's agent clients in Ping within 30 seconds.
- **AC-7.9** — Archive with any active agent returns 409 and lists the blocking agents.
- **AC-7.10** — Every state transition produces exactly one `domain_events` row.

---

### 4.8 FR-8 — Agent onboarding and starter kit

#### 4.8.1 Overview

Agent onboarding is the process by which a Domain Admin or Agent Developer registers a specific agent under an existing domain. For MVP, every agent is classified as highest-risk and receives the full input and output filter chains; there is no tiered risk model. On successful registration, AI Hub provisions an OAuth client-credentials identity at Ping and generates a downloadable starter kit containing everything the developer needs to make their first successful call.

Agent onboarding diverges from domain onboarding on approval authority. Agents requesting only Standard-tier models can be approved entirely by the Domain Admin. Agents requesting any Restricted-tier model require both Domain Admin acknowledgment and Platform Admin approval (the "double-key" flow). Agents under a low-data-classification domain (tier 1 or 2) cannot request Restricted-tier models at all; such requests are rejected automatically at submission time.

#### 4.8.2 State machine

```
  [none]
    │  POST /v1/domains/{id}/agents (submit)
    ▼
  [SUBMITTED]
    │                                               reject
    │  approve (domain admin for Standard;          ▲
    │   domain admin + platform admin for           │
    │   Restricted)                                 │
    ▼                                               │
  [PROVISIONING] ─────────────────────────────▶ [REJECTED]  (terminal)
    │
    │  Ping client minted, starter kit built
    ▼
  [ACTIVE]  ◀──── POST /resume ──── [SUSPENDED]
    │                                    ▲
    │  POST /suspend                     │
    └────────────────────────────────────┘
    │
    │  POST /archive (30 days inactive or platform admin override)
    ▼
  [ARCHIVED]  (terminal)
```

#### 4.8.3 Registration form fields

| Field | Type | Required | Validation |
|---|---|---|---|
| `agent_name` | string | Y | 3..64 chars, unique within domain. |
| `description` | text | Y | 20..1000 chars. |
| `requested_models` | array\<string\> | Y | At least one logical `model_id`. Restricted-tier requires elevated approval; auto-rejected if parent domain is tier 1 or 2. |
| `expected_rpm` | int | Y | 1..10000; must be ≤ `domain.rpm_ceiling`. |
| `expected_tpm` | int | Y | 1..10,000,000; must be ≤ `domain.tpm_ceiling`. |
| `owner_email` | string | Y | Must be a member of the parent domain (primary or secondary owner, or any user with the domain-developer Ping group). |
| `cocontributor_emails` | array\<string\> | N | Up to 10 additional Agent Developer accounts; must resolve in Ping. |
| `runtime_environment` | enum | Y | `{aws_ecs, aws_lambda, aws_eks, on_prem, other}`. Captured for audit and operational triage. |

#### 4.8.4 Approval matrix

| Requested models | Domain tier | Approver |
|---|---|---|
| All Standard-tier only | Any | Domain Admin |
| Includes Restricted-tier | 3 or 4 (Confidential or Restricted) | Domain Admin + Platform Admin |
| Includes Restricted-tier | 1 or 2 (Public or Internal) | **Rejected at submission** |

#### 4.8.5 Starter-kit contents

On successful provisioning, the Registration Service generates a starter-kit ZIP file uploaded to the starter-kits S3 bucket and exposed to the submitter via a one-time signed URL with 24-hour expiry. The ZIP contains the files listed below, each with the agent's specific IDs and defaults pre-filled. Once the signed URL has been accessed — or the 24-hour expiry passes — the ZIP becomes irretrievable and the only way to recover the `client_secret` is to rotate it.

| File | Purpose |
|---|---|
| `README.md` | Getting-started walkthrough. Includes `domain_id`, `agent_id`, step-by-step first-call instructions. |
| `credentials.env` | OAuth `client_id` and `client_secret` as environment variables. Large warning banner about single-delivery semantics. |
| `openapi.yaml` | OpenAPI 3.1 specification of `POST /v1/inference` and `GET /v1/models`. |
| `python/aihub_client.py` + `example.py` | Minimal Python client using `requests`. Demonstrates token acquisition, caching, refresh, example inference call. |
| `typescript/aihubClient.ts` + `example.ts` | Minimal TypeScript client using `fetch`. |
| `policies/applied_guardrails.md` | Human-readable description of filters applied to this agent and representative reason codes, with guidance on reducing false positives. |
| `limits/limits.json` | Assigned RPM, TPM, and the domain's current monthly spend cap. |
| `sandbox/README.md` | Instructions for using the sandbox endpoint to test before going to production. |

#### 4.8.6 Happy-path narrative

An Agent Developer logs into the domain dashboard for `fraud-analytics`. They click "Register a new agent" and fill out the form: `agent_name = "anomaly-summarizer"`, `description = "Summarizes anomaly clusters from the daily fraud-detection run"`, `requested_models = ["claude-haiku-4-5"]`, `expected_rpm = 30`, `expected_tpm = 60000`, `owner_email` = their own, `runtime_environment = aws_ecs`. The domain is tier 3 and the requested model is Standard, so the form validator accepts the submission. The agent record is created with `state = SUBMITTED` and the Domain Admin is notified by email.

The Domain Admin reviews the submission, verifies the expected RPM/TPM are reasonable, and clicks Approve. The agent transitions to `PROVISIONING` and the provisioning job runs.

Provisioning mints a Ping OAuth client. The `client_id` and `client_secret` are captured. The starter-kit generator renders all files with the agent's specific IDs, zips them, and uploads to S3. A one-time signed URL is generated. The agent transitions to `ACTIVE`. The developer receives an email with the signed URL.

The developer downloads the ZIP, sets `credentials.env` in their deployment pipeline (storing the secret in their own Secrets Manager), deploys the agent, and makes the first call successfully within 30 minutes of Domain Admin approval. End-to-end from submission to first successful call: less than 2 hours.

#### 4.8.7 Exception paths

**E8.1 — Agent name conflict.**
- *Trigger:* `agent_name` duplicates an existing agent in the same domain.
- *Detection:* Postgres `UNIQUE (domain_id, name)`.
- *Behavior:* Rejected.
- *Observable:* HTTP 409 `error.code = "agent_name_conflict"`.
- *Audit:* None.

**E8.2 — Cannot onboard under suspended domain.**
- *Trigger:* Parent domain is not `ACTIVE`.
- *Detection:* Pre-check.
- *Behavior:* Rejected.
- *Observable:* HTTP 403 `error.code = "domain_not_active"`.
- *Audit:* None.

**E8.3 — Restricted model under low-tier domain.**
- *Trigger:* `requested_models` contains Restricted-tier model; parent domain is tier 1 or 2.
- *Detection:* Form validator.
- *Behavior:* Rejected at submission (no Platform Admin involvement possible).
- *Observable:* HTTP 400 `error.code = "restricted_model_not_eligible"` with `error.message` explaining the tier requirement.
- *Audit:* None.

**E8.4 — RPM or TPM over domain ceiling.**
- *Trigger:* `expected_rpm > domain.rpm_ceiling` or `expected_tpm > domain.tpm_ceiling`.
- *Detection:* Form validator.
- *Behavior:* Rejected.
- *Observable:* HTTP 400 `error.code = "limit_above_ceiling"`, `error.field` naming which limit.
- *Audit:* None.

**E8.5 — Ping client creation fails.**
- *Trigger:* During provisioning, Ping returns 5xx when creating the OAuth client.
- *Detection:* Provisioning job.
- *Behavior:* Provisioning retries up to 3 times with exponential backoff. On exhaustion, agent remains in `PROVISIONING`; operational alert fires. Previously-completed provisioning steps are not rolled back (nothing material precedes Ping client creation).
- *Observable:* Agent stays in `PROVISIONING` longer than usual; developer sees spinning state.
- *Audit:* `agent_events` rows for each attempt.

**E8.6 — Starter-kit upload fails.**
- *Trigger:* S3 upload of ZIP fails during provisioning.
- *Detection:* Provisioning job.
- *Behavior:* Retried up to 3 times. If still failing, agent remains in `PROVISIONING`. Note: the Ping client has already been created at this point. Rollback is **not automatic** — Platform Engineering triages and either retries manually or revokes the Ping client and restarts.
- *Observable:* Agent stays in `PROVISIONING`.
- *Audit:* `agent_events` rows.

**E8.7 — Second starter-kit download attempt.**
- *Trigger:* An actor attempts to download the starter-kit ZIP a second time within the 24-hour expiry.
- *Detection:* The signed URL redirects through a Dashboard API endpoint that records the first download and invalidates subsequent attempts.
- *Behavior:* Second attempt returns 410.
- *Observable:* HTTP 410 `error.code = "starter_kit_already_downloaded"`. Developer must rotate the secret to recover.
- *Audit:* `agent_events` row on each download attempt.

**E8.8 — Secret rotation during in-flight traffic.**
- *Trigger:* Secret rotation requested while agent has live traffic using the old secret.
- *Detection:* N/A — expected rotation design.
- *Behavior:* Old secret remains valid for 1 hour (grace period). New secret immediately usable. Agent performs rolling deployment. Existing tokens continue to function until 1-hour expiry.
- *Observable:* No visible customer impact.
- *Audit:* `agent_events` row for rotation.

**E8.9 — Revocation with in-flight tokens.**
- *Trigger:* Revocation while tokens are in flight.
- *Detection:* N/A.
- *Behavior:* Ping refuses new token issuance immediately. Existing tokens remain valid for up to 1 hour. If immediate cutoff is required, Platform Admin additionally suspends the agent record in AI Hub — Core API rejects inference calls with 403 even though Kong JWT validation passes.
- *Observable:* New token attempts fail; existing inference calls continue briefly.
- *Audit:* `agent_events` rows for revocation and suspension.

**E8.10 — Archive before 30-day inactivity.**
- *Trigger:* Attempting to archive an agent with recent activity.
- *Detection:* Pre-check on `agents.last_invoked_at`.
- *Behavior:* Rejected unless caller is Platform Admin (override).
- *Observable:* HTTP 409 `error.code = "agent_recently_active"`.
- *Audit:* None.

#### 4.8.8 Acceptance criteria

- **AC-8.1** — Valid submission by an Agent Developer creates a record in `SUBMITTED` and notifies the Domain Admin by email within 60 seconds.
- **AC-8.2** — Domain Admin approval with only Standard-tier models transitions the record to `PROVISIONING` immediately.
- **AC-8.3** — Domain Admin approval with a Restricted-tier model queues the request for Platform Admin review; agent remains in `SUBMITTED` until Platform Admin approves.
- **AC-8.4** — Submission with a Restricted-tier model under a tier-1 or tier-2 domain is rejected at submission with `error.code = "restricted_model_not_eligible"`.
- **AC-8.5** — Provisioning mints a Ping OAuth client, writes `client_id` to the agent record, and builds the starter-kit ZIP.
- **AC-8.6** — The starter-kit signed URL is a one-time-use URL with 24-hour expiry; the second download attempt returns 410.
- **AC-8.7** — After `PROVISIONING` completes, `agent.state = ACTIVE` and the agent can obtain Ping tokens.
- **AC-8.8** — Suspending an agent disables its Ping client within 30 seconds.
- **AC-8.9** — Archiving an agent with `last_invoked_at` more recent than 30 days is rejected unless the caller is Platform Admin.
- **AC-8.10** — Every state transition produces exactly one `agent_events` row.

---

### 4.9 FR-9 — Rate limits and spend caps

#### 4.9.1 Overview

Rate limits and spend caps are AI Hub's quantitative safety net. They protect Bedrock quota shared across the organization, prevent a buggy agent from burning a month of budget in a day, and give domains predictable cost exposure.

Three layers are in MVP:

1. **Per-agent RPM (requests per minute)** — coarse defense against runaway traffic volume.
2. **Per-agent TPM (tokens per minute, input + output combined)** — finer defense against expensive single-call patterns (e.g., small prompts requesting large completions).
3. **Per-domain monthly spend cap in USD** — budget safety net preventing a single domain from exceeding its allocated Bedrock spend.

RPM is enforced at Kong using its built-in sliding-window counter. TPM and spend are enforced at AI Hub Core because they require knowing the request's projected tokens (input estimation) and cost (tokens × price). All enforcement is fail-closed except the Redis-backed RPM and TPM stores, which fail-open to preserve availability — the spend cap, implemented against Postgres, acts as the backstop.

#### 4.9.2 Limits and defaults

| Limit | Scope | Window | Default | Configurable by |
|---|---|---|---|---|
| RPM | Agent | Rolling 60s | 60 | Platform Admin (any); Domain Admin (up to domain ceiling) |
| TPM | Agent | Rolling 60s | 100,000 | Same |
| Monthly spend cap | Domain | Calendar month UTC | Tier-dependent (below) | Platform Admin only |

**Default monthly spend caps by domain tier:**

| Tier | Default cap | Note |
|---|---|---|
| 1 (Public) | $1,000 | Lowest risk; small cap suitable for experimentation. |
| 2 (Internal) | $5,000 | |
| 3 (Confidential) | $20,000 | |
| 4 (Restricted) | $50,000 | Executive attestation required at onboarding. |

#### 4.9.3 Enforcement algorithm

The enforcement algorithm has three phases: **pre-check**, **post-update**, and **alert**.

**Pre-check** runs after authentication and before Bedrock invocation. For RPM, Kong increments a sliding-window counter; if the incremented value exceeds the limit, the request is rejected with 429 and `Retry-After`. For TPM, Core API estimates input tokens using a tokenizer (tiktoken or Anthropic tokenizer for Claude models; choice recorded per model in the policy store) and projects `current_window + input_estimate + max_tokens`. If projection exceeds limit, rejected with 429. For spend, Core API queries domain's month-to-date spend from Postgres, projects `additional_cost = projected_tokens × price_per_1k / 1000`, rejects if projection exceeds cap.

**Post-update** runs after Bedrock returns successfully (or the output filter chain rejects). At that point the actual `input_tokens` and `output_tokens` are known. Redis `INCRBY` adds the true tokens to the TPM counter, overwriting the earlier projection. Postgres `UPDATE` adds the true cost to the domain's month-to-date spend. Both updates are synchronous — part of the response latency — but bounded (each typically under 5ms).

**Alert ladder** fires emails and dashboard banners at 80%, 95%, and 100% of monthly spend cap. 80% is early warning to Domain Admin. 95% additionally notifies Platform Admin. 100% hard-rejects with 429 `spend_cap_exceeded` and produces a distinct alert. Domain Admin can file a cap-raise request via dashboard; Platform Admin reviews and either grants a `spend_cap_override` (with `additional_usd` and explicit `expires_at`, defaulting to end-of-month) or rejects.

```
// Pseudocode for the Core API enforcement loop

func CheckAndReserve(req) Verdict {
  // 1. Estimate input tokens
  input_est = Tokenizer(req.model_id).encode(req.system + req.messages).length
  projected_tokens = input_est + (req.inference_params.max_tokens ?? 1024)

  // 2. RPM (Kong already enforced; Core double-checks)
  // ---  skipped here, enforced at the edge

  // 3. TPM
  window_sum = RedisSumBuckets(agent.id, last_60s)
  if window_sum + projected_tokens > agent.tpm_limit:
      return Reject(429, "rate_limit_tpm")

  // 4. Spend cap
  price = PolicyStore.price_per_1k(req.model_id)
  projected_cost = projected_tokens * price / 1000
  mtd_spend = Postgres.getMonthToDateSpend(domain.id)
  active_override = Postgres.getActiveOverride(domain.id)
  effective_cap = domain.monthly_cap_usd + (active_override?.additional_usd ?? 0)
  if mtd_spend + projected_cost > effective_cap:
      return Reject(429, "spend_cap_exceeded")

  return Allow{ projected_tokens, projected_cost }
}

func PostUpdate(req, resp, reservation) {
  actual_tokens = resp.usage.total_tokens
  actual_cost = ComputeCost(req.model_id, resp.usage)
  RedisINCRBY(key_for(agent.id, current_second), actual_tokens)
  Postgres.addSpend(domain.id, actual_cost)
  CheckThresholds(domain.id)  // fire 80% / 95% / 100% alerts if crossed
}
```

#### 4.9.4 Happy-path narrative

An agent makes a request with estimated input tokens of 482 and `max_tokens = 1024`, for projected total 1506. Current 60-second TPM window sum is 12,400; agent's TPM limit is 100,000; projection to 13,906 is well within limit. Model price is $0.25 per 1,000 input tokens + $1.25 per 1,000 output tokens, so conservative projected cost is `1506 × $1.25 / 1000 = $1.88` (conservative use of output price is documented; v1.1 may refine using separate per-field prices). Domain's month-to-date spend is $2,340.12 against $5,000 cap with no active override; projection to $2,342.00 is within cap.

All three checks pass. Bedrock returns 1,503 actual tokens at actual cost $1.67 (`482 × $0.00025 + 1021 × $0.00125`). Post-update: Redis `INCRBY` for 1503 on the TPM counter; Postgres `UPDATE` adds $1.67 to `mtd_spend`. No threshold crossed.

#### 4.9.5 Exception paths

**E9.1 — RPM exceeded.**
- *Trigger:* Incoming request would push the agent over 60 RPM in the rolling window.
- *Detection:* Kong sliding-window counter.
- *Behavior:* Rejected at edge. Not forwarded to Core. No TPM impact, no spend, no audit record.
- *Observable:* HTTP 429 `error.code = "rate_limit_rpm"` with `Retry-After`.
- *Audit:* Kong access log; Prometheus `aihub_rate_limit_hits_total{limit_type="rpm"}`.

**E9.2 — TPM exceeded on projection.**
- *Trigger:* Projected tokens would push agent over TPM.
- *Detection:* Core API entitlement check.
- *Behavior:* Rejected before Bedrock. No spend.
- *Observable:* HTTP 429 `error.code = "rate_limit_tpm"` with `Retry-After`.
- *Audit:* Audit record `outcome = "rejected_rate"`.

**E9.3 — Spend cap exceeded on projection.**
- *Trigger:* Projected cost would push domain over monthly cap.
- *Detection:* Core API entitlement check against Postgres `mtd_spend`.
- *Behavior:* Rejected before Bedrock.
- *Observable:* HTTP 429 `error.code = "spend_cap_exceeded"`.
- *Audit:* `outcome = "rejected_cap"`.

**E9.4 — 80% threshold crossed.**
- *Trigger:* Post-update sum crosses 80% of cap for the first time this month.
- *Detection:* Post-update threshold checker.
- *Behavior:* Email to Domain Admin; dashboard banner added.
- *Observable:* Out-of-band signal; no request-level change.
- *Audit:* `domain_events` row `event_type = 'spend_threshold_80'`.

**E9.5 — 95% threshold crossed.**
- *Trigger:* Post-update sum crosses 95%.
- *Detection:* Post-update threshold checker.
- *Behavior:* Email to Domain Admin and Platform Admin; dashboard warning.
- *Observable:* Out-of-band.
- *Audit:* `domain_events` row `event_type = 'spend_threshold_95'`.

**E9.6 — Cap lowered mid-month below current spend.**
- *Trigger:* Platform Admin reduces a domain's `monthly_cap_usd` below current `mtd_spend`.
- *Detection:* Post-reduction, the next request's projection exceeds the new cap.
- *Behavior:* Next request rejected immediately with `spend_cap_exceeded`. No retroactive action on prior successful requests (cannot be unwound).
- *Observable:* Existing agents stop receiving allowance until Platform Admin raises the cap or applies override.
- *Audit:* `domain_events` row for cap change; subsequent rejections per E9.3.

**E9.7 — Redis unavailable.**
- *Trigger:* ElastiCache Redis is unreachable.
- *Detection:* Redis client timeout (100ms).
- *Behavior:* RPM and TPM checks **fail-open** — request allowed without rate limiting. Spend-cap check (Postgres-backed) is unaffected; if Postgres also unavailable, see E9.8.
- *Observable:* No caller-visible change. Operational alert.
- *Audit:* Metric `aihub_ratelimit_failopen_total` incremented.

**E9.8 — Postgres unavailable.**
- *Trigger:* Aurora Postgres writer is unreachable.
- *Detection:* Database client timeout.
- *Behavior:* Spend-cap check and entitlement check **fail-closed**.
- *Observable:* HTTP 503 `error.code = "dependency_unavailable"`.
- *Audit:* No record (cannot write one).

**E9.9 — Override grant.**
- *Trigger:* Platform Admin grants a `spend_cap_override` with `additional_usd` and `expires_at`.
- *Detection:* Dashboard action writes to `spend_cap_overrides`.
- *Behavior:* Next request's `effective_cap` includes the override.
- *Observable:* Dashboard reflects new cap; Domain Admin notified.
- *Audit:* `domain_events` row `event_type = 'override_granted'`.

#### 4.9.6 Acceptance criteria

- **AC-9.1** — A 61st request in 60 seconds (default 60 RPM) is rejected with 429 `error.code = "rate_limit_rpm"` and `Retry-After` header.
- **AC-9.2** — A request whose projected tokens would exceed TPM is rejected with 429 `error.code = "rate_limit_tpm"` without invoking Bedrock.
- **AC-9.3** — Actual token usage is added to the TPM counter after Bedrock returns, replacing the projection.
- **AC-9.4** — A request that would push monthly spend over the cap is rejected with 429 `error.code = "spend_cap_exceeded"` without invoking Bedrock.
- **AC-9.5** — At 80% of monthly cap the Domain Admin receives exactly one email and the dashboard shows a banner.
- **AC-9.6** — Spend calculation uses the Bedrock public per-1000-token prices stored in the policy store (refreshed daily).
- **AC-9.7** — Redis outage causes RPM and TPM checks to allow traffic (fail-open); spend-cap check is unaffected.
- **AC-9.8** — Postgres outage causes entitlement and spend-cap checks to fail-closed with 503.
- **AC-9.9** — Platform Admin can grant a `spend_cap_override`; override is audit-logged, has `expires_at`, applies to subsequent projections.
- **AC-9.10** — Threshold alerts (80%, 95%, 100%) fire at most once per domain per calendar month.

---

### 4.10 FR-10 — Per-agent model allowlist

#### 4.10.1 Overview

Every agent has an explicit allowlist of logical model IDs it is permitted to invoke. The default is deny: an agent with no allowlist entries cannot call any model. New agents are created with exactly one allowlist entry — `claude-haiku-4-5` — regardless of what was requested on the registration form; additional models must be approved through the allowlist-change workflow.

The allowlist mechanism is distinct from the model catalog. The catalog is the global list of models AI Hub knows how to call; the allowlist is the per-agent subset of the catalog that the agent is authorized to call. Both are enforced — an unknown catalog entry cannot be added to an allowlist, and a catalog-valid model not in the allowlist cannot be called.

Allowlist changes use a request/approval workflow, not direct mutation. Every change is represented by an `allowlist_request` record with a `submitted_by`, a `justification`, and explicit decisions by Domain Admin and (if Restricted-tier) Platform Admin. The allowlist itself is only mutated when an `APPROVED` state is reached.

#### 4.10.2 Data model

```sql
agent_model_allowlist (
  agent_id           UUID REFERENCES agents(id),
  model_id           VARCHAR(64) NOT NULL,
  approved_at        TIMESTAMPTZ NOT NULL,
  approved_by        UUID NOT NULL,
  approval_level     VARCHAR(32) NOT NULL,  -- 'domain_admin' or 'platform_admin'
  PRIMARY KEY (agent_id, model_id)
)

allowlist_requests (
  id                 UUID PRIMARY KEY,
  agent_id           UUID REFERENCES agents(id),
  model_id           VARCHAR(64) NOT NULL,
  action             VARCHAR(8) NOT NULL,   -- 'add' or 'remove'
  justification      TEXT NOT NULL,
  submitted_by       UUID NOT NULL,
  submitted_at       TIMESTAMPTZ NOT NULL,
  domain_admin_decision    VARCHAR(16),    -- 'approved' | 'rejected' | NULL
  platform_admin_decision  VARCHAR(16),    -- 'approved' | 'rejected' | NULL
  decided_at         TIMESTAMPTZ,
  state              VARCHAR(16) NOT NULL   -- 'SUBMITTED' | 'APPROVED' | 'REJECTED'
)
```

#### 4.10.3 Approval flow

**Standard-tier models:**

1. Agent Developer submits `POST /v1/agents/{id}/allowlist-requests` with `model_id`, `action = "add"`, and `justification`.
2. A row is inserted into `allowlist_requests` with `state = SUBMITTED`, `domain_admin_decision = NULL`.
3. Domain Admin receives email notification.
4. Domain Admin approves: `state` transitions to `APPROVED`, row inserted into `agent_model_allowlist`, agent notified.
5. Domain Admin rejects: `state` transitions to `REJECTED`, row not inserted, agent notified with reason.

**Restricted-tier models:**

1. Same submission. `state = SUBMITTED`.
2. Domain Admin reviews and either rejects (terminal) or acknowledges. Acknowledgment sets `domain_admin_decision = "approved"` but does not transition `state`.
3. Platform Admin receives notification upon Domain Admin acknowledgment.
4. Platform Admin approves: both decisions present, `state = APPROVED`, row inserted into `agent_model_allowlist` with `approval_level = "platform_admin"`.
5. Platform Admin rejects: `state = REJECTED`.

All transitions are audit-logged in `agent_events` with timestamp, actor, and justification.

#### 4.10.4 Removal flow

Removal is simpler — only Domain Admin or Platform Admin may initiate, no escalation required. A `DELETE /v1/agents/{id}/allowlist/{model_id}` is processed immediately: the `agent_model_allowlist` row is deleted and an `agent_events` row captures the action.

In-flight requests for that model complete normally (the check happens at request admission time; once admitted, the request proceeds). New requests for the removed model are rejected with 403 `model_not_allowed`.

#### 4.10.5 Happy-path narrative

An Agent Developer wants to add `claude-sonnet-4-6` (Standard-tier) to their agent's allowlist. They submit via the dashboard. The Domain Admin receives notification and, after brief review of the justification, clicks Approve. The allowlist is updated; the Agent Developer is notified. Within 30 seconds of approval, the agent can call the new model.

For a Restricted model (`claude-opus-4-7`), the Developer submits, the Domain Admin acknowledges (confirming appropriateness for the agent's use case), and the request is forwarded to Platform Admin. Platform Admin reviews the justification against organizational policy (e.g., is this agent's workload one that genuinely requires Opus-class capability?) and approves or rejects. On approval, allowlist is updated.

#### 4.10.6 Exception paths

**E10.1 — Request for model not in catalog.**
- *Trigger:* `model_id` in the request is unknown.
- *Detection:* Policy Store lookup.
- *Behavior:* Rejected at submission.
- *Observable:* HTTP 400 `error.code = "invalid_model_id"`.
- *Audit:* None.

**E10.2 — Request for restricted model under low-tier domain.**
- *Trigger:* `model_id` is Restricted; parent domain is tier 1 or 2.
- *Detection:* Pre-check.
- *Behavior:* Rejected at submission (no Platform Admin involvement possible).
- *Observable:* HTTP 400 `error.code = "restricted_model_not_eligible"`.
- *Audit:* None.

**E10.3 — Double-approval race.**
- *Trigger:* Two Platform Admins approve the same Restricted-tier request simultaneously.
- *Detection:* Postgres unique constraint prevents duplicate `agent_model_allowlist` rows.
- *Behavior:* Second approval attempt receives 409 `error.code = "request_already_decided"`.
- *Observable:* Both dashboards show the request as `APPROVED` after page refresh.
- *Audit:* The first approval is the authoritative one; the second attempt is logged as a no-op in `agent_events`.

**E10.4 — In-flight requests during removal.**
- *Trigger:* Removal occurs while agent has in-flight inference calls for the removed model.
- *Detection:* N/A — expected behavior.
- *Behavior:* In-flight calls complete normally. New calls for the removed model rejected with 403.
- *Observable:* Transient period of some calls succeeding and others failing with `model_not_allowed`.
- *Audit:* Normal audit records for successful calls; new rejections audit-logged.

**E10.5 — Approval while agent suspended.**
- *Trigger:* Allowlist-request approval action on an agent in `SUSPENDED` state.
- *Detection:* Pre-check on agent state.
- *Behavior:* Allowed — the allowlist is mutated, but the agent cannot call anything until resumed. This is intentional: allowlist management should not depend on agent runtime state.
- *Observable:* Allowlist reflects the approval; agent remains non-callable until resumed.
- *Audit:* Standard `agent_events` row.

#### 4.10.7 Acceptance criteria

- **AC-10.1** — Default allowlist for a new agent is exactly `["claude-haiku-4-5"]`.
- **AC-10.2** — A request with a `model_id` not on the agent's allowlist returns 403 `error.code = "model_not_allowed"`.
- **AC-10.3** — Domain Admin can add a Standard-tier model to an agent's allowlist without escalation; the change is effective within 30 seconds.
- **AC-10.4** — Adding a Restricted-tier model requires both Domain Admin acknowledgment and Platform Admin approval; partial approval does not update the allowlist.
- **AC-10.5** — Removing a model from the allowlist is immediate; in-flight requests for that model complete normally; new requests are rejected with 403.
- **AC-10.6** — Allowlist history is queryable via `GET /v1/agents/{id}/allowlist-history`.
- **AC-10.7** — Attempting to add a Restricted-tier model under a tier-1 or tier-2 domain is rejected at submission with `error.code = "restricted_model_not_eligible"`.

---

### 4.11 FR-11 — Platform engineer dashboard

#### 4.11.1 Overview

The platform engineer dashboard provides Platform Admins with a system-wide view across all domains and agents. It is the operational command center for AI Hub. Its purpose is threefold: give operators real-time visibility into traffic health; expose the approval queues that require Platform Admin action; and provide drill-down from aggregate metrics to specific requests for investigation.

The dashboard is a single-page web application hosted at `platform.aihub.<env>.example.com` with access restricted to users bearing the Platform Admin role. It consumes the Dashboard API exclusively — it does not have direct database access.

Data freshness targets are specified in the acceptance criteria. Aggregated metrics can be up to 60 seconds stale (they are materialized views refreshed on a schedule); guardrail events and other streaming signals must be under 15 seconds stale.

#### 4.11.2 Views

| View | Content |
|---|---|
| **Overview** | Current request rate (hub-wide), error rate, guardrail block rate, total current-month spend, count of active domains and agents. |
| **Domains** | Paginated list of all domains with state, owner, current-month spend vs. cap, agent count. Drill-down to per-domain view. |
| **Agents** | Paginated list of all agents across all domains. Filters by domain, state, model. Drill-down to agent view. |
| **Guardrail events** | Stream of recent BLOCK events across all domains with filter, reason code, domain, agent. |
| **Infrastructure health** | Live status of Kong, Core API, Redis, Postgres, OpenSearch, S3, Bedrock (per region). Latency panels (p50/p95/p99) per component. |
| **Spend** | Spend breakdown by domain, agent, model. Month-to-date and 30-day rolling. |
| **Approval queue** | Pending domain registrations, pending Restricted-tier agent approvals, pending allowlist requests for Restricted-tier models, pending cap-raise requests. |
| **Policy** | Current content policy, PII categories enabled, model catalog. Read-only in MVP; edits via Platform Admin API. |
| **Overrides** | Active spend-cap overrides, their creator, expiry, reason. |

#### 4.11.3 Backing APIs

| Endpoint | Purpose |
|---|---|
| `GET /v1/dashboard/overview` | System KPIs. |
| `GET /v1/dashboard/domains` | Paginated domain list with aggregates. |
| `GET /v1/dashboard/agents` | Paginated agent list with aggregates. |
| `GET /v1/dashboard/events?type=guardrail_block` | Recent guardrail events. |
| `GET /v1/dashboard/health` | Backend health summary. |
| `GET /v1/dashboard/spend?granularity=domain\|agent\|model` | Spend aggregates. |
| `GET /v1/dashboard/approval-queue` | Items pending Platform Admin action. |

All Dashboard API endpoints require `aihub:dashboard` scope and enforce Platform Admin role in the middleware. The response envelope is consistent: `{ data: [...], pagination: { ... }, generated_at: ISO8601 }`.

#### 4.11.4 Happy-path narrative

A Platform Admin logs in. The overview loads: request rate 23.5 RPS, error rate 0.4%, guardrail block rate 2.1%, month-to-date spend $14,812 across all domains, 5 active domains, 18 active agents. They click on "Approval queue" and see 2 pending domain registrations and 1 pending Restricted-tier agent approval. They act on the domain registrations first, reviewing each and approving both; on refresh, the queue shows 1 item remaining. They then review the Restricted-tier agent request, read the justification, and approve; the queue clears.

#### 4.11.5 Exception paths

**E11.1 — Dashboard data stale.**
- *Trigger:* A required materialized view failed to refresh.
- *Detection:* Dashboard API checks `generated_at` against a maximum-age threshold.
- *Behavior:* Dashboard displays a yellow banner "Data may be up to X minutes old" with the actual age.
- *Observable:* Operators see stale-data warning rather than wrong data.
- *Audit:* Operational alert fires if staleness exceeds SLA.

**E11.2 — Backing store unavailable.**
- *Trigger:* Postgres read replica or OpenSearch is unreachable.
- *Detection:* Dashboard API.
- *Behavior:* The affected view returns 503; unaffected views continue to work.
- *Observable:* HTTP 503 from specific endpoints; partial dashboard functionality.
- *Audit:* Operational alert.

**E11.3 — Non-admin accesses platform dashboard.**
- *Trigger:* A user without Platform Admin role attempts to load `platform.aihub.<env>.example.com`.
- *Detection:* Dashboard API middleware.
- *Behavior:* All endpoints return 403.
- *Observable:* Dashboard displays "Access denied" page.
- *Audit:* Access attempt logged.

#### 4.11.6 Acceptance criteria

- **AC-11.1** — All views load within 2 seconds under nominal load.
- **AC-11.2** — Aggregated metrics are no more than 60 seconds stale; guardrail events are < 15 seconds stale.
- **AC-11.3** — Drill-down from a domain row navigates to a scoped domain view.
- **AC-11.4** — Only Platform Admins can access the dashboard; non-admin tokens receive 403.
- **AC-11.5** — Approval queue shows all pending items requiring Platform Admin action.

---

### 4.12 FR-12 — Domain owner dashboard

#### 4.12.1 Overview

The domain owner dashboard provides Domain Admins with visibility into their own domain only. Its purpose is self-service: Domain Admins should be able to understand their agents' behavior, manage their credentials, respond to guardrail events, and track spend against cap without needing to file tickets with Platform Engineering.

The dashboard is hosted at `<domain_name>.aihub.<env>.example.com` or (equivalently) `aihub.<env>.example.com/domains/<domain_id>`. All data access is strictly partition-scoped: Domain Admin of domain A cannot see any data from domain B. The Dashboard API middleware enforces this by injecting a `domain_id = <caller's domain>` clause into every query.

Agent Developers also have access but with a further filter: they see only the agents they own or co-own. All other data is blank.

#### 4.12.2 Views

| View | Content |
|---|---|
| **Overview** | Request volume, error rate, guardrail block rate, current-month spend vs. cap — domain-scoped. |
| **Agents** | All agents in the domain with state, model allowlist, current RPM/TPM, recent events. |
| **Audit trail (model access)** | Paginated, filterable list of inference requests (ID, agent, model, timestamp, outcome). Links to per-request detail showing the PII-scrubbed payload. |
| **Guardrail events** | Violations within the domain with filter, reason, agent, timestamp. |
| **Spend** | Domain spend by agent and model, with 30-day trend. |
| **Allowlist changes** | Pending and recent allowlist change requests. |
| **Credential management** | List of agent `client_id`s and rotation/revocation controls. |

#### 4.12.3 Backing APIs (domain-scoped)

| Endpoint | Purpose |
|---|---|
| `GET /v1/domains/{id}/overview` | Domain KPIs. |
| `GET /v1/domains/{id}/agents` | Agents in domain. |
| `GET /v1/domains/{id}/audit` | Request-level audit trail. |
| `GET /v1/domains/{id}/guardrail-events` | Guardrail events in domain. |
| `GET /v1/domains/{id}/spend` | Spend aggregates. |
| `GET /v1/domains/{id}/allowlist-requests` | Pending allowlist changes. |
| `POST /v1/agents/{id}/rotate-secret` | Rotate an agent credential (owned agent). |
| `POST /v1/agents/{id}/revoke` | Revoke an agent credential. |

Every one of these endpoints performs a partition check: the path `{id}` must match the caller's `domain_id` claim (or the caller must be Platform Admin). A mismatch is E6.2 (cross-partition access attempt).

#### 4.12.4 Happy-path narrative

A Domain Admin logs in. Their dashboard loads the overview for their own domain: 180 RPS over the last hour, 0.2% error rate, 3.5% guardrail block rate, $2,340 of $5,000 cap consumed. They click on Agents and see their 4 agents. They click on `anomaly-summarizer` and see 15 minutes of request history. One request shows a guardrail block; they click for detail and see the PII-scrubbed prompt and the filter verdict. They identify a pattern in prompts causing false positives, discuss with the Agent Developer, and resolve by adjusting the prompt template.

#### 4.12.5 Exception paths

**E12.1 — Cross-partition access attempt.**
- *Trigger:* A URL with the wrong `domain_id` is accessed (e.g., via bookmark manipulation).
- *Detection:* Dashboard API middleware.
- *Behavior:* Rejected.
- *Observable:* HTTP 403 `error.code = "out_of_scope_partition"`. Dashboard renders "Access denied" page.
- *Audit:* Audit record written against the caller's partition (per FR-6).

**E12.2 — Agent Developer sees another agent's data.**
- *Trigger:* A Developer navigates to an agent they don't own or co-own.
- *Detection:* Further row-level filter in Dashboard API for the `agent_developer` role.
- *Behavior:* Agent detail endpoint returns 403 or empty data; the UI hides that agent entirely in list views.
- *Observable:* Developer sees only their agents.
- *Audit:* Standard access logging.

**E12.3 — Large audit trail query.**
- *Trigger:* Domain Admin queries audit trail with a wide date range against high-traffic domain.
- *Detection:* Dashboard API enforces max 30 days per query.
- *Behavior:* Query rejected if range > 30 days; suggest using audit extract instead.
- *Observable:* HTTP 400 `error.code = "query_range_too_large"` with suggestion to use `POST /v1/audit/extracts`.
- *Audit:* None.

#### 4.12.6 Acceptance criteria

- **AC-12.1** — Domain Admin A loading the dashboard sees only domain A's data.
- **AC-12.2** — Every API call is scoped in the query layer; a request for a different domain's data returns 403 regardless of any client-side state.
- **AC-12.3** — Audit trail search returns within 3 seconds for queries spanning up to 30 days at 1M requests/month.
- **AC-12.4** — Per-request detail view shows PII-scrubbed payload and filter verdicts.
- **AC-12.5** — Agent Developer sees only their own or co-owned agents.
- **AC-12.6** — Cross-partition access attempts are audit-logged per FR-6.

---

### 4.13 FR-13 — Audit ledger

#### 4.13.1 Overview

The audit ledger is the system of record for compliance reporting and forensic investigation. It records every request, response, and policy violation across all agents in a domain-partitioned, immutable form. The ledger's guarantees are central to AI Hub's value proposition: if AI Hub is the only path to Bedrock, the ledger is the complete evidence trail.

Three guarantees are enforced:

1. **Completeness.** Every `/v1/inference` call produces exactly one audit record — whether the request succeeded, failed in a filter, hit a rate limit, or errored in Bedrock. There is no code path through Core API that produces a Bedrock invocation without a corresponding audit record.
2. **Immutability.** Once written, a record cannot be modified or deleted before its retention expires. This is enforced at storage layer (S3 Object Lock in Compliance mode) and at API layer (no UPDATE or DELETE endpoints).
3. **Partition isolation.** Domain A's records are accessible only to principals scoped to domain A (Domain Admins, Auditors scoped to A) and to Platform Admins. Separate KMS keys per domain enforce this at the encryption layer in addition to the access-control layer.

#### 4.13.2 Storage architecture

The ledger uses three cooperating stores:

| Store | Contents | Retention |
|---|---|---|
| **S3 (Object Lock, Compliance mode)** | Encrypted request and response payloads, one object per request. Per-domain KMS key. | 13 months in S3 Standard-IA, then lifecycle to Glacier Deep Archive for 7 years total. |
| **OpenSearch Service** | Queryable index: `request_id`, `domain_id`, `agent_id`, `model_id`, timestamps, token counts, cost, latency, `filter_verdicts`, `outcome`. No payloads. | 13 months (aligned with S3 hot tier). |
| **Postgres (operational)** | Reference counts, extract-job state, retention-policy configuration. | Indefinite (small). |

#### 4.13.3 Partitioning

Partitioning is logical, keyed by `domain_id`:

- **S3 key layout:** `s3://<bucket>/audit/v1/domain=<domain_id>/date=<yyyy-mm-dd>/request_id=<ulid>.json.enc`
- **OpenSearch index alias:** `audit-<domain_id>-<yyyy-mm>` (rolled monthly).
- **KMS:** one customer-managed key per domain. Key policy restricts decrypt to (a) Platform Admin role, (b) Auditors scoped to that domain, (c) Domain Admins for their own records.

#### 4.13.4 Audit record fields

| Field | Type | Notes |
|---|---|---|
| `request_id` | string (ULID) | Primary key. |
| `domain_id` | UUID | Partition key. |
| `agent_id` | UUID | |
| `user_sub` | string, nullable | Null for `agent_runtime`. |
| `client_id` | string, nullable | Null for user-initiated calls. |
| `timestamp_request` | timestamptz | When request arrived at Kong. |
| `timestamp_response` | timestamptz | When response was emitted. |
| `model_id` | string | Logical. |
| `model_arn` | string | Resolved Bedrock ARN. |
| `input_tokens` | int | |
| `output_tokens` | int | |
| `total_tokens` | int | |
| `cost_usd` | decimal(12,6) | Calculated from token counts × price. |
| `latency_ms_hub` | int | Hub overhead. |
| `latency_ms_bedrock` | int, nullable | |
| `latency_ms_total` | int | |
| `outcome` | enum | `allowed` \| `rejected_input` \| `rejected_output` \| `rejected_rate` \| `rejected_cap` \| `rejected_auth` \| `error` |
| `filter_verdicts` | json | Array of each filter's verdict. |
| `error_code` | string, nullable | Null on success. |
| `payload_s3_key` | string | Pointer to encrypted payload object. |
| `metadata` | json, nullable | Caller-supplied envelope. |

Full JSON schema in [Appendix C](#appendix-c--audit-record-json-schema).

#### 4.13.5 Write path narrative

The Audit Writer is invoked at the end of every request, regardless of outcome. It composes the record in the following steps:

1. **Compose metadata row.** All fields above except `payload_s3_key` are assembled in memory.
2. **Compose payload.** The full request body and response body (if any) are JSON-encoded into a single object with structure `{ request: {...}, response: {...} }`. For rejected requests, the response is `null` or the filter-rejection envelope.
3. **Encrypt payload.** A fresh AES-256 data key is generated. The payload is encrypted with that data key. The data key is wrapped with the per-domain KMS CMK using `kms:GenerateDataKey`. The output is a single encrypted blob containing the wrapped key and the ciphertext.
4. **Upload to S3.** `PutObject` to `s3://<bucket>/audit/v1/domain=<domain_id>/date=<yyyy-mm-dd>/request_id=<ulid>.json.enc` with `x-amz-object-lock-retention-until-date` set to the configured retention date.
5. **Index to OpenSearch.** The metadata row (with `payload_s3_key` referencing the uploaded object) is written to the current-month OpenSearch index.
6. **Both writes must succeed.** If either fails, the request fails with 503 `audit_unavailable` (see E1.14). A best-effort write to a local dead-letter journal is attempted for reconciliation.

Both writes are synchronous from the caller's perspective. Total write latency budget: 1000ms (S3 typically ~150ms, OpenSearch ~80ms; budget includes retries).

#### 4.13.6 MVP extract

Auditors and Domain Admins may request a time-bounded extract of audit records for their scope.

**Submit:** `POST /v1/audit/extracts` with `{ domain_id?, from_ts, to_ts, format: "ndjson"|"csv", include_payloads: bool }`.

**Eligibility:**
- Auditor (any scope in their assignment),
- Domain Admin (own domain only),
- Platform Admin (any domain or global).

**Execution:** Async job; produces a signed S3 URL with 24-hour expiry, delivered via email.

**Payload decryption:** If `include_payloads=true`, the job decrypts via the per-domain KMS key using the requester's IAM context — which requires the requester's role to include decrypt permission on that key (enforced by the key policy).

**Auditing the auditors:** Extract jobs themselves are audit-logged. Each extract creates a row in an `audit_extracts` table with requester, scope, parameters, job state, and delivery URL.

#### 4.13.7 Immutability guarantees

- S3 bucket configured with Object Lock in **Compliance mode** with default retention period matching the archival policy. Object Lock in Compliance mode cannot be bypassed even by the root account.
- No API is exposed that can modify or delete an audit record before retention expiry. Only AWS root account with break-glass MFA could override, explicitly out of normal operational scope.
- OpenSearch writes are append-only; there is no UPDATE or DELETE path in the Audit Writer. The Audit Writer's IAM role has `opensearch:PutIndex` but not `DeleteIndex` or update permissions on individual documents.
- A daily **integrity job** compares the count of S3 objects to the count of OpenSearch records per partition and alerts on drift.

#### 4.13.8 Happy-path narrative

An inference request completes (either successfully or with a guardrail block). The Audit Writer is invoked. It composes the record, generates a fresh data key via KMS, encrypts the payload, uploads to S3 (156ms), indexes to OpenSearch (82ms), returns. Total audit write time: ~240ms including the KMS call. The Core API emits the response to the caller.

Months later, a Compliance investigator requests an audit extract for domain `fraud-analytics` for April 2026 with payloads. The extract job runs, decrypts each object using the domain KMS key (which the investigator's Auditor role has access to via key policy), streams the decrypted records to NDJSON, uploads to a temporary S3 location, and emails a signed URL. The investigator downloads the NDJSON within 24 hours.

#### 4.13.9 Exception paths

**E13.1 — S3 write fails.**
- *Trigger:* `PutObject` returns 5xx or times out.
- *Detection:* Audit Writer.
- *Behavior:* Retried up to 3 times with exponential backoff. On exhaustion, request fails with 503.
- *Observable:* HTTP 503 `error.code = "audit_unavailable"`.
- *Audit:* Dead-letter journal entry written locally; operational alert fires.

**E13.2 — OpenSearch write fails.**
- *Trigger:* OpenSearch index operation returns 5xx or times out.
- *Detection:* Audit Writer.
- *Behavior:* Retried up to 3 times. On exhaustion, request fails with 503. Note: S3 write may have succeeded; the orphaned S3 object is reconciled by the daily integrity job.
- *Observable:* HTTP 503 `error.code = "audit_unavailable"`.
- *Audit:* Dead-letter journal entry.

**E13.3 — Partial write (S3 success, OpenSearch failure).**
- *Trigger:* S3 succeeds but OpenSearch fails after all retries.
- *Detection:* Audit Writer final state.
- *Behavior:* S3 object remains (cannot be deleted under Object Lock). Caller receives 503. The orphan is detected by the daily integrity job, which writes a catch-up record to OpenSearch referencing the existing S3 object.
- *Observable:* Immediate: 503 to caller. Eventually: the record appears in OpenSearch once the integrity job runs.
- *Audit:* Dead-letter journal initially; integrity job logs the catch-up.

**E13.4 — Cross-domain extract attempt.**
- *Trigger:* Auditor scoped to domain A requests an extract for domain B.
- *Detection:* Extract API middleware.
- *Behavior:* Rejected.
- *Observable:* HTTP 403 `error.code = "out_of_scope_partition"`.
- *Audit:* Attempt logged; auditors are auditable.

**E13.5 — Integrity drift detected.**
- *Trigger:* Daily integrity job finds count mismatch between S3 and OpenSearch in a partition.
- *Detection:* Integrity job.
- *Behavior:* Drift emitted to `aihub_audit_integrity_drift_count` metric; P1 alert fires.
- *Observable:* Operational alert.
- *Audit:* Drift report written to `audit_integrity_reports` table.

**E13.6 — Large extract.**
- *Trigger:* Extract request spans a very large date range or very high-volume domain.
- *Detection:* Extract API projects the result size.
- *Behavior:* If projected size > 10 GB, the request is accepted but split into multiple output files with a manifest; URL expiry is extended to 72 hours.
- *Observable:* Extract job takes longer; delivery email includes a manifest file.
- *Audit:* Standard extract-job audit.

#### 4.13.10 Acceptance criteria

- **AC-13.1** — Every call to `/v1/inference` produces exactly one audit record regardless of outcome.
- **AC-13.2** — If audit write fails, the request fails with 503 `error.code = "audit_unavailable"` and the response is not delivered.
- **AC-13.3** — Domain A's audit records are not visible to Domain B's Domain Admin (tested via deliberate cross-domain query).
- **AC-13.4** — A payload object cannot be deleted or overwritten (S3 Object Lock test).
- **AC-13.5** — An Auditor scoped to domain A can extract domain A's records but not domain B's.
- **AC-13.6** — The daily integrity job runs and emits `aihub_audit_integrity_drift_count`.
- **AC-13.7** — Extract jobs are themselves audit-logged.
- **AC-13.8** — Retrieving an encrypted payload requires a principal with decrypt permission on the per-domain KMS key.

---

### 4.14 FR-14 — Fail-behavior contract

#### 4.14.1 Overview

The fail-behavior matrix below is the authoritative, per-dependency contract for how AI Hub responds when a dependency fails or times out. Any dependency not listed here defaults to fail-closed. This matrix is the single source of truth — the rationale for each row is stated because an operator reading runbooks, an auditor reviewing controls, and an engineer adding a new dependency all need to understand why the choice was made, not just what the choice was.

#### 4.14.2 The matrix

| Dependency / filter | Timeout | On timeout | On error | HTTP code | Rationale |
|---|---|---|---|---|---|
| Ping JWT validation (signature) | 500 ms | Fail-closed | Fail-closed | 401 | Auth is non-negotiable. |
| Ping JWKS refresh | 1 s | Use cached (24h max) | Use cached (24h max) | — | Keeps hub operational during Ping maintenance. |
| Prompt injection filter | 300 ms | Fail-closed | Fail-closed | 503 | Safety critical. |
| PII scanner (input) | 300 ms | Fail-closed | Fail-closed | 503 | Safety critical. |
| Content policy (input) | 300 ms | Fail-closed | Fail-closed | 503 | Safety critical. |
| Bedrock invoke | 30 s | 504 to caller | 502 to caller | 504 / 502 | Upstream surfaced. |
| PII scrub (output) | 300 ms | Fail-closed | Fail-closed | 502 | Safety critical. |
| Harmful content (output) | 300 ms | Fail-closed | Fail-closed | 502 | Safety critical. |
| Policy compliance (output) | 300 ms | Fail-closed | Fail-closed | 502 | Safety critical. |
| Audit ledger write | 1 s | Fail-closed | Fail-closed | 503 | Compliance: no unlogged calls. |
| Rate-limit counter (Redis) | 100 ms | **Fail-open** | **Fail-open** | — | Spend cap is Postgres-backed safety net. |
| Spend-cap evaluator (Postgres) | 200 ms | Fail-closed | Fail-closed | 503 | Financial control. |
| Postgres (entitlement) | 200 ms | Fail-closed | Fail-closed | 503 | Cannot verify allowlist without it. |

#### 4.14.3 Commentary on the audit fail-closed stance

The audit-ledger-write fail-closed stance is the most consequential operational choice in this document. If the ledger has a bad day, the entire hub goes down. This is deliberate because the ledger is the evidence trail for compliance, and producing Bedrock invocations without corresponding audit records would defeat one of AI Hub's core guarantees.

The alternative — **fail-open-with-DLQ**, where audit writes go to a durable queue and the hub continues if the queue accepts, with the queue drained asynchronously — is defensible and much easier to operate. It is tracked as a v1.1 candidate pending explicit Compliance sign-off. This PRD does not assume that sign-off; MVP ships with fail-closed.

#### 4.14.4 Commentary on the rate-limit fail-open stance

Redis unavailability is the one fail-open entry. The rationale: rate limiting is an operational protection (protect Bedrock quota, prevent runaway traffic), not a safety or compliance protection. Brief periods where rate limiting is not enforced are acceptable because the per-domain monthly spend cap — backed by Postgres, which has different failure characteristics from Redis — provides the absolute backstop against runaway cost. If both Redis and Postgres are unavailable simultaneously, the spend-cap evaluator falls back to fail-closed.

#### 4.14.5 Acceptance criteria

- **AC-14.1** — Every row of the matrix has a corresponding automated fault-injection test in the chaos suite.
- **AC-14.2** — A synthetic Ping unavailability exercise (JWKS endpoint blocked) continues to serve traffic for up to 24 hours, then fails with 503.
- **AC-14.3** — A synthetic audit-write failure causes the request to fail with 503 and does not deliver the Bedrock response.
- **AC-14.4** — A synthetic Redis outage causes rate-limit checks to allow traffic (fail-open) but the spend cap check remains enforced.

---

## 5. Data model

All operational data lives in a single Aurora Postgres cluster. Audit payloads live in S3 (section 4.13); audit metadata lives in OpenSearch. Redis holds only transient rate-limit counters. Flyway manages schema migrations.

### 5.1 Tables

```sql
-- Domains
CREATE TABLE domains (
    id                        UUID PRIMARY KEY,
    name                      VARCHAR(64) NOT NULL UNIQUE,
    business_unit             VARCHAR(128) NOT NULL,
    primary_owner_user_id     UUID NOT NULL REFERENCES users(id),
    secondary_owner_user_id   UUID NOT NULL REFERENCES users(id),
    cost_center               CHAR(8) NOT NULL,
    data_classification_tier  SMALLINT NOT NULL CHECK (data_classification_tier BETWEEN 1 AND 4),
    state                     VARCHAR(16) NOT NULL,
    monthly_cap_usd           DECIMAL(12,2) NOT NULL,
    rpm_ceiling               INT NOT NULL DEFAULT 1000,
    tpm_ceiling               INT NOT NULL DEFAULT 1000000,
    kms_key_arn               VARCHAR(512),
    intended_use_summary      TEXT NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (state IN ('SUBMITTED','PROVISIONING','ACTIVE','SUSPENDED','ARCHIVED','REJECTED')),
    CHECK (primary_owner_user_id <> secondary_owner_user_id)
);

-- Agents
CREATE TABLE agents (
    id                    UUID PRIMARY KEY,
    domain_id             UUID NOT NULL REFERENCES domains(id),
    name                  VARCHAR(64) NOT NULL,
    description           TEXT NOT NULL,
    owner_user_id         UUID NOT NULL REFERENCES users(id),
    state                 VARCHAR(16) NOT NULL,
    ping_client_id        VARCHAR(128),
    rpm_limit             INT NOT NULL DEFAULT 60,
    tpm_limit             INT NOT NULL DEFAULT 100000,
    runtime_environment   VARCHAR(16) NOT NULL,
    last_invoked_at       TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (domain_id, name),
    CHECK (state IN ('SUBMITTED','PROVISIONING','ACTIVE','SUSPENDED','ARCHIVED','REJECTED')),
    CHECK (runtime_environment IN ('aws_ecs','aws_lambda','aws_eks','on_prem','other'))
);
CREATE INDEX idx_agents_domain ON agents(domain_id);
CREATE INDEX idx_agents_state ON agents(state) WHERE state IN ('SUBMITTED','PROVISIONING');

-- Per-agent model allowlist
CREATE TABLE agent_model_allowlist (
    agent_id         UUID NOT NULL REFERENCES agents(id),
    model_id         VARCHAR(64) NOT NULL,
    approved_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_by      UUID NOT NULL REFERENCES users(id),
    approval_level   VARCHAR(32) NOT NULL,
    PRIMARY KEY (agent_id, model_id),
    CHECK (approval_level IN ('domain_admin','platform_admin'))
);

-- Agent co-contributors
CREATE TABLE agent_cocontributors (
    agent_id      UUID NOT NULL REFERENCES agents(id),
    user_id       UUID NOT NULL REFERENCES users(id),
    added_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (agent_id, user_id)
);

-- Allowlist change requests
CREATE TABLE allowlist_requests (
    id                        UUID PRIMARY KEY,
    agent_id                  UUID NOT NULL REFERENCES agents(id),
    model_id                  VARCHAR(64) NOT NULL,
    action                    VARCHAR(8) NOT NULL,
    justification             TEXT NOT NULL,
    submitted_by              UUID NOT NULL REFERENCES users(id),
    submitted_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    domain_admin_decision     VARCHAR(16),
    domain_admin_decided_by   UUID REFERENCES users(id),
    domain_admin_decided_at   TIMESTAMPTZ,
    platform_admin_decision   VARCHAR(16),
    platform_admin_decided_by UUID REFERENCES users(id),
    platform_admin_decided_at TIMESTAMPTZ,
    state                     VARCHAR(16) NOT NULL,
    CHECK (action IN ('add','remove')),
    CHECK (state IN ('SUBMITTED','APPROVED','REJECTED')),
    CHECK (domain_admin_decision IS NULL OR domain_admin_decision IN ('approved','rejected')),
    CHECK (platform_admin_decision IS NULL OR platform_admin_decision IN ('approved','rejected'))
);

-- Domain lifecycle events (audit trail for the domain record itself)
CREATE TABLE domain_events (
    id              UUID PRIMARY KEY,
    domain_id       UUID NOT NULL REFERENCES domains(id),
    event_type      VARCHAR(48) NOT NULL,
    actor_user_id   UUID REFERENCES users(id),
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_domain_events_domain_time ON domain_events(domain_id, created_at DESC);

-- Agent lifecycle events
CREATE TABLE agent_events (
    id              UUID PRIMARY KEY,
    agent_id        UUID NOT NULL REFERENCES agents(id),
    domain_id       UUID NOT NULL REFERENCES domains(id),
    event_type      VARCHAR(48) NOT NULL,
    actor_user_id   UUID REFERENCES users(id),
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_agent_events_agent_time ON agent_events(agent_id, created_at DESC);

-- Policies (versioned)
CREATE TABLE policies (
    id              UUID PRIMARY KEY,
    policy_type     VARCHAR(32) NOT NULL,
    version         INT NOT NULL,
    document        JSONB NOT NULL,
    effective_from  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      UUID NOT NULL REFERENCES users(id),
    UNIQUE (policy_type, version),
    CHECK (policy_type IN ('content_policy','pii_categories','model_catalog','pricing'))
);

-- Spend cap overrides
CREATE TABLE spend_cap_overrides (
    id              UUID PRIMARY KEY,
    domain_id       UUID NOT NULL REFERENCES domains(id),
    additional_usd  DECIMAL(12,2) NOT NULL,
    reason          TEXT NOT NULL,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_by      UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at      TIMESTAMPTZ,
    revoked_by      UUID REFERENCES users(id)
);
CREATE INDEX idx_overrides_active ON spend_cap_overrides(domain_id)
    WHERE revoked_at IS NULL;

-- Domain monthly spend (materialized, updated on each request)
CREATE TABLE domain_monthly_spend (
    domain_id   UUID NOT NULL REFERENCES domains(id),
    month_utc   DATE NOT NULL,  -- first day of month
    spend_usd   DECIMAL(14,6) NOT NULL DEFAULT 0,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain_id, month_utc)
);

-- Users (cached from Ping; authoritative store is Ping)
CREATE TABLE users (
    id              UUID PRIMARY KEY,
    ping_sub        VARCHAR(128) NOT NULL UNIQUE,
    email           VARCHAR(256) NOT NULL UNIQUE,
    display_name    VARCHAR(256),
    auditor_scope   JSONB,  -- for Auditor role: ['*'] or list of domain_ids
    last_synced_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Audit extract jobs
CREATE TABLE audit_extracts (
    id              UUID PRIMARY KEY,
    requested_by    UUID NOT NULL REFERENCES users(id),
    domain_id       UUID,       -- NULL = global (Platform Admin)
    from_ts         TIMESTAMPTZ NOT NULL,
    to_ts           TIMESTAMPTZ NOT NULL,
    format          VARCHAR(16) NOT NULL,
    include_payloads BOOLEAN NOT NULL DEFAULT FALSE,
    state           VARCHAR(16) NOT NULL,
    delivery_s3_key VARCHAR(1024),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    CHECK (format IN ('ndjson','csv')),
    CHECK (state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED'))
);
```

### 5.2 Non-Postgres data

- **Redis (ElastiCache):** keys of the form `rl:rpm:<agent_id>:<window>` and `rl:tpm:<agent_id>:<window>`, integer values, 2-minute TTL.
- **S3 (audit payloads):** encrypted JSON objects; keyed by `audit/v1/domain=<domain_id>/date=<yyyy-mm-dd>/request_id=<ulid>.json.enc`.
- **OpenSearch:** one index alias per domain per month, `audit-<domain_id>-<yyyy-mm>`; field mapping per Appendix C.

---

## 6. API contracts

All endpoints are HTTPS only. All endpoints except `/v1/health` and `/v1/ready` require a Bearer JWT. The full scope/role matrix is in Appendix B.

### 6.1 Inference

| Method | Path | Scope | Role |
|---|---|---|---|
| POST | `/v1/inference` | `aihub:invoke` | Agent Runtime |
| GET | `/v1/models` | `aihub:invoke` | Agent Runtime |
| GET | `/v1/health` | (none) | (anonymous) |
| GET | `/v1/ready` | (none) | (anonymous) |

### 6.2 Domain management

| Method | Path | Scope | Role |
|---|---|---|---|
| POST | `/v1/domains` | `aihub:dashboard` | Any authenticated user |
| GET | `/v1/domains` | `aihub:admin` | Platform Admin |
| GET | `/v1/domains/{id}` | `aihub:domain` | Domain Admin (own) / Platform Admin |
| POST | `/v1/domains/{id}/approve` | `aihub:admin` | Platform Admin |
| POST | `/v1/domains/{id}/reject` | `aihub:admin` | Platform Admin |
| POST | `/v1/domains/{id}/suspend` | `aihub:admin` | Platform Admin |
| POST | `/v1/domains/{id}/resume` | `aihub:admin` | Platform Admin |
| POST | `/v1/domains/{id}/archive` | `aihub:admin` | Platform Admin |

### 6.3 Agent management

| Method | Path | Scope | Role |
|---|---|---|---|
| POST | `/v1/domains/{id}/agents` | `aihub:dashboard` | Domain Admin / Agent Developer |
| GET | `/v1/domains/{id}/agents` | `aihub:domain` | Domain Admin (own) / Platform Admin |
| GET | `/v1/agents/{id}` | `aihub:domain` | Domain Admin / Agent Developer (owned) / Platform Admin |
| POST | `/v1/agents/{id}/approve` | `aihub:domain` | Domain Admin (Standard only); Platform Admin (Restricted) |
| POST | `/v1/agents/{id}/reject` | `aihub:domain` | Domain Admin / Platform Admin |
| POST | `/v1/agents/{id}/suspend` | `aihub:domain` | Domain Admin (own) / Platform Admin |
| POST | `/v1/agents/{id}/resume` | `aihub:domain` | Domain Admin / Platform Admin |
| POST | `/v1/agents/{id}/archive` | `aihub:domain` | Domain Admin (30d inactive) / Platform Admin |
| POST | `/v1/agents/{id}/rotate-secret` | `aihub:domain` | Domain Admin / Agent Developer (own) |
| POST | `/v1/agents/{id}/revoke` | `aihub:domain` | Domain Admin / Platform Admin |

### 6.4 Allowlist management

| Method | Path | Scope | Role |
|---|---|---|---|
| GET | `/v1/agents/{id}/allowlist` | `aihub:domain` | Domain Admin / Agent Developer (own) |
| POST | `/v1/agents/{id}/allowlist-requests` | `aihub:domain` | Agent Developer / Domain Admin |
| POST | `/v1/allowlist-requests/{id}/domain-acknowledge` | `aihub:domain` | Domain Admin |
| POST | `/v1/allowlist-requests/{id}/approve` | `aihub:admin` | Platform Admin (Restricted-tier final approval) |
| POST | `/v1/allowlist-requests/{id}/reject` | `aihub:domain` | Domain Admin / Platform Admin |
| DELETE | `/v1/agents/{id}/allowlist/{model_id}` | `aihub:domain` | Domain Admin / Platform Admin |

### 6.5 Dashboard read

| Method | Path | Scope | Role |
|---|---|---|---|
| GET | `/v1/dashboard/overview` | `aihub:dashboard` | Platform Admin |
| GET | `/v1/dashboard/domains` | `aihub:dashboard` | Platform Admin |
| GET | `/v1/dashboard/approval-queue` | `aihub:dashboard` | Platform Admin |
| GET | `/v1/domains/{id}/overview` | `aihub:dashboard` | Domain Admin / Platform Admin |
| GET | `/v1/domains/{id}/audit` | `aihub:dashboard` | Domain Admin / Platform Admin |
| GET | `/v1/domains/{id}/guardrail-events` | `aihub:dashboard` | Domain Admin / Platform Admin |
| GET | `/v1/domains/{id}/spend` | `aihub:dashboard` | Domain Admin / Platform Admin |

### 6.6 Audit

| Method | Path | Scope | Role |
|---|---|---|---|
| POST | `/v1/audit/extracts` | `aihub:audit` | Auditor / Platform Admin |
| GET | `/v1/audit/extracts` | `aihub:audit` | Auditor / Platform Admin |
| GET | `/v1/audit/extracts/{id}` | `aihub:audit` | Auditor / Platform Admin |
| GET | `/v1/audit/records` | `aihub:audit` | Auditor / Platform Admin |

### 6.7 Policy and overrides

| Method | Path | Scope | Role |
|---|---|---|---|
| GET | `/v1/policies/{type}` | `aihub:admin` | Platform Admin |
| POST | `/v1/policies/{type}` | `aihub:admin` | Platform Admin |
| POST | `/v1/domains/{id}/spend-cap-override` | `aihub:admin` | Platform Admin |
| DELETE | `/v1/domains/{id}/spend-cap-override/{id}` | `aihub:admin` | Platform Admin |

---

## 7. Non-functional requirements

### 7.1 Latency

| Metric | Target |
|---|---|
| Hub overhead (p50) | ≤ 300 ms |
| Hub overhead (p95) | ≤ 800 ms |
| Hub overhead (p99) | ≤ 1,500 ms |
| End-to-end (p95, small prompt) | ≤ 3 s |
| End-to-end (p95, Haiku, typical workload) | ≤ 5 s |

Hub overhead is defined as `latency_ms.total - latency_ms.bedrock`. It includes Kong edge processing, entitlement, filter chain time (both directions), and audit write.

### 7.2 Availability

| Component | SLO |
|---|---|
| Inference API (`/v1/inference`) | 99.9% monthly |
| Dashboards | 99.5% monthly (excluding planned maintenance) |
| Audit write | 99.95% monthly |
| Extract job completion | ≤ 4 hours for extracts up to 100 GB decrypted |

### 7.3 Scalability

- Steady-state: 100 requests per second hub-wide.
- Burst: 300 RPS for up to 10 minutes (auto-scaling).
- 10,000 registered agents across 500 domains.
- 1 billion audit records in the hot tier (13 months).

### 7.4 Security

- TLS 1.2+ for all external endpoints; TLS 1.3 preferred; 1.1 and below rejected.
- All at-rest data encrypted with AWS KMS. Per-domain CMKs for audit payloads.
- No credentials in environment variables or images; all service-to-service secrets via Secrets Manager with 90-day rotation.
- Static SAST and dependency-vulnerability scanning on every CI build.

### 7.5 Data retention

- **Audit payloads (S3):** 13 months in S3 Standard-IA; lifecycle to Glacier Deep Archive; total retention 7 years.
- **Audit index (OpenSearch):** 13 months.
- **Operational logs:** 90 days.
- **User accounts (cache):** resynced from Ping daily.

---

## 8. Observability specification

### 8.1 Metrics (Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `aihub_requests_total` | counter | `outcome`, `model_id`, `domain_id` |
| `aihub_request_duration_ms` | histogram | `outcome`, `model_id` |
| `aihub_filter_duration_ms` | histogram | `filter`, `outcome` |
| `aihub_guardrail_blocks_total` | counter | `filter`, `direction`, `reason_code` |
| `aihub_rate_limit_hits_total` | counter | `limit_type` |
| `aihub_spend_threshold_events_total` | counter | `domain_id`, `threshold` |
| `aihub_bedrock_duration_ms` | histogram | `model_id`, `outcome` |
| `aihub_bedrock_errors_total` | counter | `model_id`, `error_type` |
| `aihub_audit_write_duration_ms` | histogram | `store` (s3\|opensearch) |
| `aihub_audit_write_failures_total` | counter | `store`, `reason` |
| `aihub_audit_integrity_drift_count` | gauge | `partition` |
| `aihub_ratelimit_failopen_total` | counter | (none) |
| `aihub_jwks_stale_seconds` | gauge | (none) |

### 8.2 Structured logs

All services emit structured JSON logs with: `timestamp`, `level`, `request_id`, `domain_id`, `agent_id`, `message`, and call-site context. PII in payloads is never written to logs. Kong access logs include `sub`, `agent_id`, status code, latency.

### 8.3 Traces

OpenTelemetry traces emitted for every inference request. Spans:

- `aihub.kong.ingress`
- `aihub.auth.jwt`
- `aihub.entitlement`
- `aihub.filter.input` (parent of per-filter spans)
- `aihub.filter.input.prompt_injection`
- `aihub.filter.input.pii_input`
- `aihub.filter.input.content_policy_input`
- `aihub.bedrock.invoke`
- `aihub.filter.output.*`
- `aihub.audit.write` (parent of per-store spans)

### 8.4 Alerts

| Alert | Condition | Severity |
|---|---|---|
| Inference error rate high | 5xx rate > 1% for 5m | P1 |
| Hub p95 latency high | `aihub_request_duration_ms` p95 > 1500 ms for 10m | P2 |
| Guardrail vendor errors | `aihub_filter_duration_ms{outcome="ERROR"}` > 10/min | P1 |
| Audit write failures | `aihub_audit_write_failures_total` > 0 | P1 |
| Audit integrity drift | `aihub_audit_integrity_drift_count` > 0 | P1 |
| JWKS stale | `aihub_jwks_stale_seconds` > 3600 | P2 |
| Spend cap approaching | any domain at ≥95% | P3 (ticketing) |
| Bedrock throttling sustained | ThrottlingException rate > 5/min for 10m | P2 |

---

## 9. Security specification

### 9.1 Threat model (abbreviated)

| Threat | Mitigation |
|---|---|
| Stolen agent credential | 1-hour token lifetime; rotation available; revoke API; all calls audit-logged. |
| Stolen dashboard session | Tokens in memory only (not localStorage); 1-hour max lifetime; backed by corporate SSO + MFA. |
| Prompt injection exfiltrating system prompt | `prompt_injection` filter; fail-closed. |
| PII leakage to Bedrock | `pii_input` filter; fail-closed. |
| Model hallucinating PII on output | `pii_output` filter; fail-closed. |
| Quota exhaustion attack | Per-agent RPM + TPM; per-domain monthly cap; alerts at 80/95/100%. |
| Audit tampering | S3 Object Lock Compliance; per-domain KMS; no delete path in API. |
| Cross-tenant data access | Row-level partition filter in Dashboard API; per-domain KMS enforces at encryption layer. |
| Guardrail bypass via malformed content blocks | Strict input schema; unsupported block types rejected. |

### 9.2 Secrets management

- All service-to-service credentials in AWS Secrets Manager with automatic rotation (90 days).
- Per-domain KMS CMKs for audit payloads; key policy restricts decrypt to authorized principals.
- No secrets in container images or environment variables.
- Agent `client_secret` stored only in Ping; delivered once to agent via single-use signed URL.

### 9.3 Network

- Kong is the sole ingress; no direct connectivity from agents to Core or Bedrock.
- VPC endpoint policies restrict Bedrock access to the AI Hub production account.
- Service Control Policies at the OU boundary remove Bedrock IAM permissions from application accounts during rollout.
- mTLS between Kong and Core (Service Mesh: AWS App Mesh or Istio).

---

## 10. Deployment and environments

### 10.1 Runtime topology

| Service | Compute | Scaling |
|---|---|---|
| Kong AI Gateway | ECS Fargate, 2 AZs | 2–16 tasks, target 60% CPU |
| AI Hub Core API | ECS Fargate, 2 AZs | 4–32 tasks, target 50% CPU |
| Registration Service | ECS Fargate | 2–4 tasks |
| Dashboard API | ECS Fargate | 2–8 tasks |
| Redis | ElastiCache cluster mode, 3 shards, multi-AZ | Fixed; scale up during capacity review |
| Postgres | Aurora Postgres, 1 writer + 2 readers, multi-AZ | Scale readers only |
| OpenSearch | Managed service, 3-node, multi-AZ | Scale via capacity review |
| S3 | Managed, per-bucket Object Lock config | N/A |

### 10.2 CI/CD

- **CI:** GitHub Actions. Lint → unit tests → integration tests → SAST → dependency scan → container build → push to ECR.
- **CD:** Atlantis + Terraform for infrastructure. Blue/green ECS deployments via CodeDeploy with automatic rollback on CloudWatch alarm.
- **DB migrations:** Flyway run as one-shot ECS task in the deploy pipeline; forward-only; rollback via forward fix.
- **Policy changes (content policy, model catalog):** separate change-management workflow with Platform Admin approval and dual-control sign-off.

### 10.3 Configuration

- **SSM Parameter Store** for non-secret config (endpoint URLs, feature flags, timeouts).
- **Secrets Manager** for all credentials and API keys.
- **Environment variable overrides** for local dev only; rejected in production images.

---

## 11. Testing and acceptance

### 11.1 Test levels

| Level | Coverage |
|---|---|
| **Unit** | ≥ 80% line coverage on Core, Registration, Dashboard services. Mocks for Bedrock, Ping, KMS. |
| **Contract** | Pact tests for Core ↔ Registration and Core ↔ Dashboard APIs. |
| **Integration** | Docker-Compose stack: Core + Redis + Postgres + LocalStack S3/KMS + OpenSearch + Ping stub. Exercise full request path. |
| **Guardrail regression** | Known-violation corpus ≥ 95% BLOCK rate; benign corpus ≤ 5% false positive. Run on every build. |
| **Load** | k6-based. Sustain 100 RPS for 30 minutes with p95 hub overhead < 800 ms. |
| **Chaos** | Fault injection per FR-14 matrix: kill Redis, kill Postgres writer, block Ping JWKS, Bedrock timeout, S3 throttling, OpenSearch blackhole. Each row has an automated test. |
| **Security** | SAST (Semgrep), dependency (Dependabot), container (Trivy), DAST (OWASP ZAP) against staging. Annual third-party pentest. |

### 11.2 Test data

- **Guardrail corpus:** curated set of known-violating prompts and outputs covering all filters, refreshed quarterly.
- **Benign corpus:** representative legitimate prompts from pilot domains, anonymized.
- **Synthetic agents:** reserved agent IDs in staging for load and regression testing.

### 11.3 Acceptance gate

No feature ships to production without:

1. All FR-level acceptance criteria from section 4 passing.
2. NFRs from section 7 verified in staging.
3. Guardrail regression targets met.
4. Chaos suite green.
5. Security scans clean (no high or critical).
6. Platform Admin sign-off.

---

## 12. Rollout plan

| Phase | Scope | Duration | Exit gate |
|---|---|---|---|
| **Alpha** | 1 pilot domain, 2 agents. Hub deployed in **shadow mode**: calls go through both hub and direct Bedrock; hub results compared with direct results for divergence. | 3 weeks | < 1% functional divergence; zero audit gaps. |
| **Beta** | 3 pilot domains, 6 agents. Hub **enforcing**; direct Bedrock still allowed. | 4 weeks | All domains satisfied; no P1 incidents for 2 weeks. |
| **GA** | Open enrollment for new domains. Existing direct-Bedrock agents encouraged to migrate. | ongoing | Steady-state operation. |
| **Hardening** | Address any feedback, tune thresholds, optimize latency. | 4 weeks (parallel with GA) | Hub overhead p95 < 800 ms met. |
| **Full cutover** | Direct Bedrock access removed via SCP + VPCe policies for all application accounts. | Cut-off date determined when ≥ 90% of Bedrock traffic is already going through hub. | 100% traffic through hub; CloudTrail reconciliation matches hub audit records. |

---

## 13. Success metrics

90 days post-GA:

- **≥ 5 domains** onboarded.
- **≥ 20 agents** onboarded.
- **≥ 90% of organizational Bedrock traffic** flowing through hub (verified by CloudTrail reconciliation).
- **≤ 1 business day** median domain-registration to first call.
- **≤ 2 hours** median agent-registration to first call.
- **p95 hub overhead ≤ 800 ms** sustained.
- **≤ 5% false positive rate** on guardrail input chain across pilot domains' representative traffic.
- **0 unlogged Bedrock calls** (verified via CloudTrail vs. hub audit record reconciliation).

---

## 14. Assumptions and open questions

### 14.1 Assumptions

1. Ping Identity (PingFederate or PingOne) is available as the sole identity provider with admin API access for automated OAuth client provisioning.
2. AWS Bedrock service quotas are sufficient for projected peak hub traffic (300 RPS burst).
3. AWS regions `us-east-1` and `eu-west-1` are the initial deployment regions; domain tier 4 (Restricted) may require data-residency enforcement — flagged as Q2 below.
4. A sandbox Bedrock endpoint (or a well-constructed mock) is available for agent developer testing (Q3).
5. Each domain has a stable `cost_center` that finance can reconcile against chargeback extracts.
6. Platform Engineering provides 24×7 operational coverage for P1 alerts.
7. Corporate SSO is federated with Ping for human user authentication.
8. AWS KMS per-domain CMK creation is within quota; request increase if > 50 domains anticipated in first year.

### 14.2 Open questions

- **Q1.** Audit write currently fail-closed per FR-14. Should v1.1 introduce a durable queue (DLQ) allowing fail-open-with-DLQ for audit writes? Requires explicit Compliance sign-off.
- **Q2.** Data residency for tier-4 domains — enforce EU-only Bedrock inference profiles? Impacts Model Router.
- **Q3.** Sandbox environment — use a mock Bedrock or a real Bedrock with lower quotas? Impacts cost and fidelity of developer testing.
- **Q4.** `cost_center` source — is there an authoritative finance system we should integrate with, or is free-text with regex sufficient for MVP?
- **Q5.** For Restricted-tier model approval, should Platform Admin be a specific team (AI CoE) or any Platform Admin? Impacts the UI and SLA.
- **Q6.** Email delivery mechanism — transactional SES from AI Hub AWS account, or corporate SMTP relay? Impacts deliverability and audit.
- **Q7.** Starter kit should include an IAM policy example for Secrets Manager access; which least-privilege template is canonical?
- **Q8.** Prompt-engineering guidelines to help developers reduce false positives — owned by AI Hub or by AI CoE?

---

## 15. Glossary

**AI Hub** — The AI Control Plane that mediates all LLM traffic between agents and AWS Bedrock.

**Agent** — A registered software system that invokes LLMs through AI Hub. Identified by `agent_id`; belongs to exactly one domain.

**Domain** — A business-unit-level tenant of AI Hub. Identified by `domain_id`; contains multiple agents; has its own spend cap, KMS key, and audit partition.

**Guardrail** — A filter that evaluates prompts or completions and returns ALLOW, BLOCK, or ERROR.

**RPM** — Requests per minute. Per-agent rate limit.

**TPM** — Tokens per minute (input + output combined). Per-agent rate limit.

**Spend cap** — Monthly USD ceiling, per domain.

**Allowlist** — Per-agent set of logical model IDs the agent is permitted to invoke.

**Bedrock** — AWS's managed foundation-model service.

**Ping** — Ping Identity; the sole OAuth 2.0 / OIDC identity provider.

**ULID** — Universally Unique Lexicographically Sortable Identifier. Used for `request_id`.

**CMK** — Customer Managed Key in AWS KMS.

**Object Lock (Compliance)** — S3 feature preventing object deletion or modification before retention expiry, with no bypass even from the root account.

---

## Appendix A — Error code catalog

| HTTP | `error.code` | Meaning |
|---|---|---|
| 400 | `invalid_request` | Schema violation; `error.field` gives JSON pointer. |
| 400 | `invalid_model_id` | `model_id` not in catalog. |
| 400 | `streaming_not_supported` | `stream=true` (MVP). |
| 400 | `content_block_not_supported` | Image/document/tool block (MVP). |
| 400 | `context_window_exceeded` | Projected tokens exceed model's window. |
| 400 | `user_not_found` | Email does not resolve in Ping. |
| 400 | `restricted_model_not_eligible` | Restricted-tier model + tier-1/2 domain. |
| 400 | `limit_above_ceiling` | Requested RPM/TPM exceeds domain ceiling. |
| 400 | `query_range_too_large` | Audit trail query > 30 days. |
| 401 | `missing_token` | No Authorization header. |
| 401 | `malformed_authorization_header` | Bad header format. |
| 401 | `invalid_token` | Signature or decoding failure. |
| 401 | `invalid_issuer` | `iss` mismatch. |
| 401 | `invalid_audience` | `aud` mismatch. |
| 401 | `token_expired` | `exp` in the past. |
| 401 | `token_not_yet_valid` | `nbf` in the future. |
| 403 | `insufficient_scope` | Token lacks required scope. |
| 403 | `model_not_allowed` | `model_id` not in agent allowlist. |
| 403 | `agent_suspended` | Agent state not ACTIVE. |
| 403 | `domain_suspended` | Domain state not ACTIVE. |
| 403 | `domain_not_active` | Parent domain not ACTIVE (onboarding). |
| 403 | `out_of_scope_partition` | Cross-partition access. |
| 409 | `domain_name_conflict` | Duplicate `domain_name`. |
| 409 | `agent_name_conflict` | Duplicate `agent_name` in domain. |
| 409 | `domain_has_active_agents` | Archive blocked by active agents. |
| 409 | `agent_recently_active` | Archive blocked by recent activity. |
| 409 | `request_already_decided` | Concurrent approval. |
| 410 | `starter_kit_already_downloaded` | Second download attempt. |
| 413 | `request_too_large` | Body exceeds 1 MB. |
| 422 | `guardrail_input_block` | Input filter BLOCK; `error.filter` identifies. |
| 429 | `rate_limit_rpm` | Per-agent RPM exceeded. |
| 429 | `rate_limit_tpm` | Per-agent TPM exceeded. |
| 429 | `spend_cap_exceeded` | Domain monthly cap exceeded. |
| 429 | `bedrock_throttled` | Bedrock ThrottlingException. |
| 502 | `guardrail_output_block` | Output filter BLOCK; `error.filter` identifies. |
| 502 | `bedrock_error` | Bedrock 5xx. |
| 503 | `guardrail_timeout` | Filter exceeded 300ms. |
| 503 | `guardrail_error` | Filter vendor error. |
| 503 | `audit_unavailable` | Audit write failed; request not delivered. |
| 503 | `auth_unavailable` | Ping JWKS stale > 24h. |
| 503 | `dependency_unavailable` | Core downstream unreachable (Postgres, etc.). |
| 503 | `idp_unavailable` | Ping admin API unavailable. |
| 504 | `bedrock_timeout` | Bedrock did not respond in 30s. |

---

## Appendix B — Complete permissions matrix

Legend: ✓ = yes; — = no; *scope* = yes with partition scoping.

| Endpoint | Platform Admin | Domain Admin | Agent Developer | Agent Runtime | Auditor |
|---|:-:|:-:|:-:|:-:|:-:|
| `POST /v1/inference` | — | — | — | ✓ | — |
| `GET /v1/models` | — | — | — | ✓ | — |
| `POST /v1/domains` | ✓ | ✓ (submit) | ✓ (submit) | — | — |
| `GET /v1/domains` | ✓ | — | — | — | — |
| `GET /v1/domains/{id}` | ✓ | *own* | — | — | *scope* |
| `POST /v1/domains/{id}/approve` | ✓ | — | — | — | — |
| `POST /v1/domains/{id}/reject` | ✓ | — | — | — | — |
| `POST /v1/domains/{id}/suspend` | ✓ | — | — | — | — |
| `POST /v1/domains/{id}/resume` | ✓ | — | — | — | — |
| `POST /v1/domains/{id}/archive` | ✓ | — | — | — | — |
| `POST /v1/domains/{id}/agents` | ✓ | *own* | *own-domain* | — | — |
| `GET /v1/domains/{id}/agents` | ✓ | *own* | *own* (filtered) | — | *scope* |
| `GET /v1/agents/{id}` | ✓ | *own* | *owned* | — | *scope* |
| `POST /v1/agents/{id}/approve` | ✓ | *own* (Std) | — | — | — |
| `POST /v1/agents/{id}/suspend` | ✓ | *own* | — | — | — |
| `POST /v1/agents/{id}/rotate-secret` | ✓ | *own* | *owned* | — | — |
| `POST /v1/agents/{id}/revoke` | ✓ | *own* | — | — | — |
| `GET /v1/agents/{id}/allowlist` | ✓ | *own* | *owned* | — | *scope* |
| `POST /v1/agents/{id}/allowlist-requests` | ✓ | *own* | *owned* | — | — |
| `POST /v1/allowlist-requests/{id}/approve` | ✓ (Restricted) | — | — | — | — |
| `DELETE /v1/agents/{id}/allowlist/{model}` | ✓ | *own* | — | — | — |
| `GET /v1/dashboard/*` | ✓ | — | — | — | — |
| `GET /v1/domains/{id}/overview` | ✓ | *own* | — | — | — |
| `GET /v1/domains/{id}/audit` | ✓ | *own* | — | — | *scope* |
| `POST /v1/audit/extracts` | ✓ | *own* | — | — | *scope* |
| `POST /v1/policies/{type}` | ✓ | — | — | — | — |
| `POST /v1/domains/{id}/spend-cap-override` | ✓ | — | — | — | — |

---

## Appendix C — Audit record JSON schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://aihub.example.com/schemas/audit-record-v1.json",
  "title": "AIHubAuditRecord",
  "type": "object",
  "required": [
    "request_id", "domain_id", "agent_id",
    "timestamp_request", "timestamp_response",
    "model_id", "outcome", "filter_verdicts",
    "latency_ms_hub", "latency_ms_total",
    "payload_s3_key", "schema_version"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "1.0" },
    "request_id":        { "type": "string", "pattern": "^[0-9A-HJKMNP-TV-Z]{26}$" },
    "domain_id":         { "type": "string", "format": "uuid" },
    "agent_id":          { "type": "string", "format": "uuid" },
    "user_sub":          { "type": ["string","null"] },
    "client_id":         { "type": ["string","null"] },
    "timestamp_request": { "type": "string", "format": "date-time" },
    "timestamp_response":{ "type": "string", "format": "date-time" },
    "model_id":          { "type": "string" },
    "model_arn":         { "type": ["string","null"] },
    "input_tokens":      { "type": ["integer","null"], "minimum": 0 },
    "output_tokens":     { "type": ["integer","null"], "minimum": 0 },
    "total_tokens":      { "type": ["integer","null"], "minimum": 0 },
    "cost_usd":          { "type": ["number","null"], "minimum": 0 },
    "latency_ms_hub":    { "type": "integer", "minimum": 0 },
    "latency_ms_bedrock":{ "type": ["integer","null"], "minimum": 0 },
    "latency_ms_total":  { "type": "integer", "minimum": 0 },
    "outcome": {
      "type": "string",
      "enum": ["allowed","rejected_input","rejected_output","rejected_rate",
               "rejected_cap","rejected_auth","error"]
    },
    "error_code":     { "type": ["string","null"] },
    "payload_s3_key": { "type": "string" },
    "filter_verdicts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["filter_name","direction","outcome","latency_ms"],
        "properties": {
          "filter_name":   { "type": "string" },
          "direction":     { "type": "string", "enum": ["input","output"] },
          "outcome":       { "type": "string", "enum": ["ALLOW","BLOCK","ERROR"] },
          "reason_code":   { "type": ["string","null"] },
          "detected_categories": {
            "type": ["array","null"],
            "items": { "type": "string" }
          },
          "latency_ms":    { "type": "integer", "minimum": 0 },
          "raw_vendor_response_ref": { "type": ["string","null"] }
        }
      }
    },
    "metadata": { "type": ["object","null"] }
  },
  "additionalProperties": false
}
```

---

*End of document.*
