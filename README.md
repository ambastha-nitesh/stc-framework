# STC Framework

**From AI Agents to AI Systems: Stalwart · Trainer · Critic**

An architectural framework for building production-grade AI agent
systems with built-in optimization, zero-trust governance, data
sovereignty, and audit-ready compliance — designed for regulated
environments (FINRA / SEC / HIPAA / GDPR).

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![AIUC-1 Aligned](https://img.shields.io/badge/AIUC--1-Aligned-green.svg)](docs/architecture/aiuc-1-crosswalk.md)

## What this solves, in one paragraph

Most AI agent frameworks ship a single agent with system prompts for
different modes and call it a system. That design fails audit: the
same process that answers a question also evaluates its own answer,
also decides whether to self-retrain, also holds the keys. STC
separates those roles into **Stalwart** (execute), **Trainer**
(optimize), **Critic** (govern), and a **Sentinel** infrastructure
layer — each with asymmetric authority enforced by module boundaries
and driven by a signed declarative spec. The result is an agent
architecture that a regulator can actually certify and a security
team can actually operate.

## Why this exists

- **Separation of duties is the product.** Regulators, especially in
  finance, require that the approver is not the actor. A
  single-process agent cannot provide that.
- **Production costs drift silently.** A framework that doesn't
  enforce per-tenant budgets and rate limits discovers problems on
  the bill, not in the control plane.
- **Audit must be a first-class artifact.** HMAC-chained, tamper-
  evident audit with per-event-class retention is load-bearing for
  SEC 17a-4 / FINRA 4511 / GDPR Art. 30.
- **Defaults matter more than features.** The default configuration
  must fail closed in prod. We enforce six invariants at startup —
  missing any one refuses to boot.

## What we considered and rejected

- **Single-class agent with role prompts.** Rejected — fails
  separation of duties; confirmation bias in self-grading.
- **Runtime-mutable config service.** Rejected — admin UIs are
  attack surfaces and undermine non-repudiation.
- **Plain SHA-256 audit chain.** Rejected — an attacker with write
  access can recompute the chain. HMAC requires the key.
- **Single retention knob for all audit events.** Rejected — a
  retention number that's right for generic queries is wrong for
  erasure receipts (6 years) and wrong for chain seals (forever).
- **"One LLM adapter to rule them all" (e.g. only LiteLLM).** Rejected
  — adapter pattern lets Bedrock-in-VPC, local Ollama, and a
  proprietary gateway all coexist without leaking infrastructure
  decisions into the business code.

## Three things most likely to surprise a new reader

1. **The mock LLM is load-bearing for tests.** `MockLLMClient` labels
   every response `[mock-llm]`. Seeing that tag in a production audit
   record is a P0 — someone bypassed the `STC_ENV=prod` guard.
2. **`erase_tenant` is either a real deletion OR a refusal.** The
   JSONL backend deletes (GDPR Art. 17). The WORM backend raises
   `ComplianceViolation` (SEC 17a-4). They're both correct, for
   different deployments. Do not try to unify them.
3. **Correlation fields live in `contextvars`, not function
   arguments.** `trace_id`, `tenant_id`, `persona` etc. flow through
   `ContextVar` instances. Logs, spans, and audit records read from
   the same snapshot. Threading these through every function
   signature would be a maintenance tax with no safety benefit.

---

## For new readers

- [Architecture](docs/ARCHITECTURE.md) — how the pieces fit, with
  Mermaid diagrams.
- [Guided tour](docs/GUIDED_TOUR.md) — 10-minute newcomer walkthrough.
- [Glossary](docs/GLOSSARY.md) — every domain term defined.
- [First-week FAQ](docs/FAQ.md) — the 13 questions people actually ask.
- [Gotchas](docs/GOTCHAS.md) — things that look like bugs but aren't.
- [Decisions](docs/DECISIONS.md) — five ADRs covering the load-bearing
  choices.
- [Runbook](docs/operations/RUNBOOK.md) — prod deployment, alerts,
  incident response.
- [Contributing](CONTRIBUTING.md) — five step-by-step recipes for the
  most common changes.

## For security / compliance reviewers

- [Security audit](docs/security/SECURITY_AUDIT.md) — cybersecurity
  review with regressions.
- [Governance audit](docs/security/GOVERNANCE_AUDIT.md) — data
  privacy, retention, DSAR, erasure; GDPR / CCPA / HIPAA / SOC 2 /
  AIUC-1 crosswalk.
- [Enterprise readiness](docs/operations/ENTERPRISE_READINESS.md) —
  observability, budget, idempotency, fail-fast startup.
- [Staff review](docs/security/STAFF_REVIEW.md) — senior code review
  rounds, pre-deployment review for regulated environments.

---

## The Problem

Most AI agents today are workers. Very few are systems.

When agents hit production, familiar problems emerge: costs quietly drift upward, accuracy regresses as models or data change, hallucinations slip through, safety and bias checks are bolted on after the fact, and when something breaks, humans become the control plane.

**What if the core problem isn't how smart our AI agents are — but how we structure them?**

## The STC Framework

STC applies software architecture discipline to AI agents. Instead of deploying a single agent and hoping it self-regulates, STC separates execution, optimization, and governance into distinct system roles:

| Persona | Role | Responsibility |
|---------|------|----------------|
| **S — Stalwart** | Execution Plane | Performs business tasks. Optimized to act — not to judge itself, retrain itself, or trust itself. |
| **T — Trainer** | Optimization & Control Plane | Makes the Stalwart better over time. Monitors performance, optimizes cost, tunes prompts, selects models. |
| **C — Critic** | Zero-Trust Governance Plane | Assumes nothing is trustworthy by default. Verifies outputs, detects hallucinations, enforces compliance. |

These are supported by two architectural layers (not agents):

| Layer | Role | Responsibility |
|-------|------|----------------|
| **Sentinel Layer** | Interoperability & Identity | Enforces trust boundaries, data classification routing, PII redaction, authentication. Infrastructure, not intelligence. |
| **Declarative Specification** | System Contract | Versioned YAML that defines what each persona can do, cost thresholds, guardrail policies, data sovereignty rules, and compliance mappings. |

### Key Principles

- **Separation of concerns**: Execution, optimization, and governance are structurally separated
- **Asymmetric authority**: These are not peers — they have distinct, non-overlapping responsibilities
- **Agents learn, infrastructure enforces**: S, T, and C evolve; the Sentinel Layer and Spec enforce policies
- **Data sovereignty by design**: Proprietary data never leaves the trust boundary
- **Audit-ready from day one**: Every action produces an immutable, traceable record
- **AIUC-1 aligned**: Designed to satisfy the world's first AI agent certification standard

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Declarative Specification                     │
│         (YAML contract: policies, thresholds, compliance)       │
└───────────┬──────────────────┬──────────────────┬───────────────┘
            │                  │                  │
    ┌───────▼───────┐  ┌──────▼───────┐  ┌───────▼───────┐
    │   STALWART    │  │   TRAINER    │  │    CRITIC     │
    │  (Execution)  │  │(Optimization)│  │ (Governance)  │
    │               │  │              │  │               │
    │  LangGraph    │  │  Agent       │  │  NeMo         │
    │  Agent        │  │  Lightning   │  │  Guardrails   │
    │  Workflow     │  │  + LiteLLM   │  │  + Guardrails │
    │               │  │  FinOps      │  │  AI Hub       │
    └───────┬───────┘  └──────┬───────┘  └───────┬───────┘
            │                  │                  │
    ┌───────▼──────────────────▼──────────────────▼───────────────┐
    │              Shared Observability Backbone                   │
    │         OpenTelemetry + Arize Phoenix + Langfuse             │
    └─────────────────────────┬───────────────────────────────────┘
                              │
    ┌─────────────────────────▼───────────────────────────────────┐
    │                     Sentinel Layer                           │
    │  LiteLLM Gateway · Presidio PII · Data Classification       │
    │  Auth/AuthZ · MCP Access Control · Boundary Audit           │
    └─────────────────────────────────────────────────────────────┘
                              │
    ┌─────────────────────────▼───────────────────────────────────┐
    │                  Data Sovereignty Layer                      │
    │  Local Vector Store (Qdrant) · Local Embeddings (Ollama)    │
    │  Tiered Routing · Surrogate Tokenization · Local LLMs       │
    └─────────────────────────────────────────────────────────────┘
```

## Open-Source Stack

| Capability | Tool | License |
|-----------|------|---------|
| Agent Execution | LangGraph | MIT |
| RL-based Optimization | Microsoft Agent Lightning | MIT |
| LLM Gateway + Cost Control | LiteLLM | Apache 2.0 |
| Guardrail Orchestration | NVIDIA NeMo Guardrails | Apache 2.0 |
| Composable Validators | Guardrails AI + Hub | Apache 2.0 |
| PII Detection + Redaction | Microsoft Presidio | MIT |
| Prompt Registry + Versioning | Langfuse | MIT |
| Observability + Audit | OpenTelemetry + Arize Phoenix | Apache 2.0 |
| Local Vector Store | Qdrant | Apache 2.0 |
| Local Embeddings + LLMs | Ollama | MIT |
| Adversarial Testing | Garak (NVIDIA) | Apache 2.0 |

## Reference Implementation: Financial Document Q&A

The repository includes a complete, production-ready reference implementation: an AI-powered financial document Q&A agent that answers questions about SEC filings, earnings reports, and compliance documents.

**Why this example?**
- It's a real enterprise problem, not a toy
- Accuracy is measurable and critical — wrong numbers in finance are liabilities
- RAG agents degrade in production — giving the Trainer real optimization surface
- Proprietary financial data must never leave the trust boundary
- AIUC-1 compliance requirements map directly to financial services

**What it demonstrates:**

| Persona | What It Does |
|---------|-------------|
| **Stalwart** | LangGraph RAG workflow: question → retrieve → reason → cite → answer |
| **Trainer** | Optimizes retrieval quality, tunes prompts via Agent Lightning, routes to cheaper models when accuracy holds |
| **Critic** | Catches hallucinated numbers, blocks PII leakage, prevents investment advice, enforces scope |
| **Sentinel** | Routes restricted data to local models, redacts PII via Presidio, enforces auth per persona |

**Measured improvement**: After running with the Trainer active, the system demonstrates measurable gains in retrieval precision, answer accuracy, and cost efficiency versus baseline.

### Install

```bash
# Minimal install — works out of the box with zero-dependency defaults
# (mock LLM, hash embedder, in-memory vector store, JSONL audit).
pip install stc-framework

# Full stack with every optional integration
pip install "stc-framework[all]"

# Just the HTTP service facade
pip install "stc-framework[service]"

# Development
pip install -e ".[dev]"
```

### Use as a library

```python
from stc_framework import STCSystem

system = STCSystem.from_spec("spec-examples/financial_qa.yaml")
result = system.query("What was Acme Corp's FY2024 revenue?")

print(result.response)
print(result.governance["action"])   # pass | warn | block | escalate
print(result.metadata["model_used"])
print(result.metadata["citations"])
```

Async consumers use `aquery`:

```python
import asyncio
from stc_framework import STCSystem

async def main():
    system = STCSystem.from_env()
    await system.astart()
    try:
        result = await system.aquery("What was revenue?", tenant_id="acme-1")
        print(result.response)
    finally:
        await system.astop()

asyncio.run(main())
```

### Run as a service

```bash
pip install -e ".[service]"
gunicorn -k gthread --threads 8 -w 4 \
    --bind 0.0.0.0:8000 \
    "stc_framework.service.wsgi:application"

curl http://localhost:8000/healthz
curl -X POST http://localhost:8000/v1/query \
    -H "X-Tenant-Id: acme-1" -H "Content-Type: application/json" \
    -d '{"query": "What was FY2024 revenue?"}'
curl http://localhost:8000/metrics
```

### Full stack with Docker

```bash
cp .env.example .env   # fill in provider keys if you want real LLMs
docker-compose up -d

# Inside your Python environment:
pip install -e ".[all]"
stc-baseline --spec spec-examples/financial_qa.yaml
stc-agent --spec spec-examples/financial_qa.yaml
```

## Configuration

The framework is configured via the declarative spec (example:
[`spec-examples/financial_qa.yaml`](spec-examples/financial_qa.yaml)) and
environment variables (prefix `STC_`):

| Variable | Default | Purpose |
|---|---|---|
| `STC_SPEC_PATH` | `spec-examples/financial_qa.yaml` | Spec to load with `STCSystem.from_env()` |
| `STC_ENV` | `dev` | `dev`, `staging`, `prod` |
| `STC_LOG_FORMAT` | `json` | `json` or `text` |
| `STC_LOG_CONTENT` | `false` | Include request/response bodies in logs (risk) |
| `STC_OTLP_ENDPOINT` | *(unset)* | OTLP gRPC endpoint for traces |
| `STC_METRICS_PORT` | `9090` | Prometheus exposition port |
| `STC_LLM_ADAPTER` | `mock` | `mock` or `litellm` |
| `STC_VECTOR_ADAPTER` | `in_memory` | `in_memory` or `qdrant` |
| `STC_EMBEDDING_ADAPTER` | `hash` | `hash`, `ollama`, `openai` |
| `STC_PRESIDIO_ENABLED` | `true` | Turn off when Presidio is unavailable |
| `STC_LLM_TIMEOUT_SEC` | `30` | Per-call LLM timeout |
| `STC_LLM_BULKHEAD` | `64` | Max concurrent LLM calls |
| `STC_LLM_CIRCUIT_FAIL_MAX` | `5` | Failures before circuit opens |

## What's new in v0.3.0 (capability completion)

v0.3.0 ports every capability previously parked in `experimental/` into
the supported `src/stc_framework/` package. All new subsystems are
**opt-in** — none runs unless the operator wires it explicitly, so
existing v0.2.0 deployments are unaffected.

Major additions:

- **Compliance** (`stc_framework.compliance`) — FINRA Rule 2210, Reg BI
  suitability, NYDFS 72-hour notification, Part 500 certification, EEOC
  bias & fairness monitor, IP risk scanner, AI transparency + consent,
  attorney-client privilege routing, fiduciary fairness, legal hold
  manager, explainability narrator, AI sovereignty (model origin, state
  AI law matrix, inference jurisdiction enforcer).
- **Risk** (`stc_framework.risk`) — ISO 31000 risk register (5×5
  matrix, full lifecycle), 12-indicator KRI engine with auto-escalation,
  risk-adjusted optimizer with four veto evaluators.
- **Security** (`stc_framework.security`) — threat detection
  (DDoS, behavioural UEBA, deception), MITRE ATLAS + OWASP LLM Top 10
  pen-test runner.
- **Orchestration** (`stc_framework.orchestration`) — multi-Stalwart
  workflow engine with capability-tag dispatch, budget cap, and an
  async state lock ready for parallel fan-out.
- **Infrastructure** (`stc_framework.infrastructure`) — pluggable
  `KeyValueStore`, session manager with atomic micro-dollar cost
  counters, SLO-aware performance testing.
- **Governance extensions** — data catalog (6-dim quality scoring),
  lineage with impact analysis, DoD-style secure destruction,
  token/burst/cost circuit breakers, rolling-mean anomaly detection.

Every subsystem routes persistent state through one `KeyValueStore`
Protocol; a Redis backend ships in v0.3.1.

See [`docs/v030_integration.md`](docs/v030_integration.md) for
integration recipes (enable FINRA enforcement, wire a risk optimizer,
register a honey token, record end-to-end lineage, block destruction
during litigation, run a load test). The staff-engineer code review of
this release, with tiered findings and fixes, is in
[`docs/security/V030_STAFF_REVIEW.md`](docs/security/V030_STAFF_REVIEW.md).

## Documentation

- [v0.3.0 integration guide](docs/v030_integration.md)
- [v0.3.0 staff review](docs/security/V030_STAFF_REVIEW.md)
- [Architecture](docs/architecture/README.md)
- [Operations](docs/operations/) — deployment, observability, resilience, scaling, multitenancy
- [Reference Implementation: Financial Q&A](src/stc_framework/reference_impl/financial_qa/)
- [Example spec](spec-examples/financial_qa.yaml)
- [AIUC-1 compliance mapping](docs/architecture/aiuc-1-crosswalk.md)

## Origin

The STC Framework was [introduced by Nitesh Ambastha](https://medium.com/@niteshambastha/from-ai-agents-to-ai-systems-introducing-the-stc-framework-b9c06a89746b) in December 2025 as an architectural pattern for bringing software engineering discipline to AI agent design. This repository is the open-source implementation of that vision, evolved to incorporate the protocol standardization wave (MCP/A2A), FinOps for AI, composable guardrails, data sovereignty, and AIUC-1 compliance alignment.

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Key areas where we need help:
- Additional Stalwart framework adapters (CrewAI, AutoGen, OpenAI Agents SDK)
- New Guardrails AI validators for domain-specific use cases
- AIUC-1 compliance evidence automation
- Adversarial testing scenarios
- Documentation and tutorials

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.

## Citation

If you use the STC Framework in your research or products, please cite:

```bibtex
@article{ambastha2025stc,
  title={From AI Agents to AI Systems: Introducing the STC Framework},
  author={Ambastha, Nitesh},
  year={2025},
  url={https://medium.com/@niteshambastha/from-ai-agents-to-ai-systems-introducing-the-stc-framework-b9c06a89746b}
}
```
