# STC Framework

**From AI Agents to AI Systems: Stalwart · Trainer · Critic**

An open-source architectural framework for building production-grade AI agent systems with built-in optimization, zero-trust governance, data sovereignty, and audit-ready compliance.

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![AIUC-1 Aligned](https://img.shields.io/badge/AIUC--1-Aligned-green.svg)](docs/aiuc-1-crosswalk/README.md)

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

### Quick Start

```bash
# Clone the repository
git clone https://github.com/stc-framework/stc-framework.git
cd stc-framework

# Copy and configure the environment
cp .env.example .env
# Edit .env with your API keys and configuration

# Start the full STC system
docker-compose up -d

# Load sample financial documents (public SEC filings)
python reference-impl/scripts/load_documents.py

# Run the baseline evaluation
python reference-impl/evaluation/run_baseline.py

# Start the interactive Q&A interface
python reference-impl/scripts/run_agent.py

# After running queries, check the Trainer's optimization dashboard
open http://localhost:6006  # Phoenix UI
open http://localhost:3000  # Langfuse UI
```

## Documentation

- [Architecture Deep Dive](docs/architecture/README.md)
- [Declarative Specification Reference](spec/README.md)
- [AIUC-1 Compliance Crosswalk](docs/aiuc-1-crosswalk/README.md)
- [Stalwart: Building Your Agent](stalwart/README.md)
- [Trainer: Optimization Guide](trainer/README.md)
- [Critic: Governance Configuration](critic/README.md)
- [Sentinel: Security & Data Sovereignty](sentinel/README.md)
- [Reference Implementation Guide](reference-impl/README.md)

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
