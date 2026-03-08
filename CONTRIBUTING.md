# Contributing to STC Framework

Thank you for your interest in contributing to the STC Framework. This project aims to bring software architecture discipline to AI agent systems, and contributions from the community are essential to making it robust and production-ready.

## Ways to Contribute

### Code Contributions
- **Stalwart framework adapters**: Add support for CrewAI, AutoGen, OpenAI Agents SDK, or Semantic Kernel
- **Guardrail validators**: Create domain-specific validators for the Guardrails AI Hub
- **Trainer optimization loops**: Implement new optimization strategies beyond GRPO
- **Adversarial testing scenarios**: Add MITRE ATLAS-informed test cases

### Documentation
- **Tutorials**: Step-by-step guides for specific use cases
- **Architecture documentation**: Deeper explanations of design decisions
- **AIUC-1 evidence automation**: Tools to generate compliance evidence

### Reference Implementations
- **New domains**: Healthcare, legal, customer service Q&A agents
- **Multi-agent scenarios**: STC systems that coordinate multiple Stalwarts

## Development Setup

```bash
git clone https://github.com/stc-framework/stc-framework.git
cd stc-framework
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Ensure the Declarative Specification schema is respected
4. Add tests for new functionality
5. Update documentation as needed
6. Submit a pull request with a clear description

## Code Style

- Python: Follow PEP 8
- YAML: 2-space indentation
- All code should include OpenTelemetry instrumentation for observability

## Architecture Principles

When contributing, keep these STC principles in mind:

1. **Separation of concerns**: Execution (Stalwart), optimization (Trainer), and governance (Critic) must remain structurally separate
2. **Agents learn, infrastructure enforces**: S, T, and C can evolve; the Sentinel Layer enforces policies
3. **Data sovereignty by design**: Proprietary data never leaves the trust boundary
4. **Audit-ready from day one**: Every action produces an immutable trace
5. **The Declarative Specification is the source of truth**: All behavior is configured through the spec, not hardcoded

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
