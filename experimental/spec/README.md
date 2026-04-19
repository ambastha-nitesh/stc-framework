# Declarative Specification

The Declarative Specification is the single source of truth for an STC system. It defines what each persona can do, how data flows, what guardrails are active, and how the system maps to compliance requirements.

## Schema

The specification is a versioned YAML file that all STC components read from. It is:

- **Immutable per version**: Changes create new versions, never modify existing ones
- **Machine-readable**: Every component parses it at startup
- **Auditable**: Version history is tracked in the prompt registry (Langfuse)
- **The compliance artifact**: AIUC-1 auditors review this as the primary governance document

## Structure

```
spec/
├── README.md              # This file
├── schema.json            # JSON Schema for validation
└── stc-spec.yaml          # The specification itself
```

## Usage

Every STC component loads the specification at startup:

```python
from stc_framework.spec import load_spec

spec = load_spec("spec/stc-spec.yaml")

# Stalwart reads its permitted tools and MCP servers
stalwart_config = spec.stalwart

# Trainer reads cost thresholds and optimization parameters
trainer_config = spec.trainer

# Critic reads guardrail configuration and escalation triggers
critic_config = spec.critic

# Sentinel reads data sovereignty and auth policies
sentinel_config = spec.sentinel
```

## Versioning

The specification uses semantic versioning. The `version` field at the top of the YAML file tracks the current version. All traces include the spec version, enabling full audit lineage.
