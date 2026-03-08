# AIUC-1 Compliance Crosswalk

This document maps every AIUC-1 requirement to the STC Framework component that satisfies it.

## Overview

[AIUC-1](https://aiuc-1.com) is the world's first AI agent standard, covering six enterprise risk domains. The STC Framework is designed so that a properly configured deployment satisfies AIUC-1 certification requirements, providing the technical controls, audit trails, and governance documentation that an accredited auditor (such as Schellman) would evaluate.

## Mapping

### A. Data & Privacy

| AIUC-1 Req | Requirement | STC Component | Evidence Source |
|-----------|------------|---------------|----------------|
| A001 | Establish input data policy | `data_sovereignty.classification` + Declarative Spec | Spec YAML + boundary audit logs |
| A002 | Establish output data policy | `critic.guardrails.output_rails` | Phoenix traces with guardrail results |
| A003 | Limit AI agent data collection | `stalwart.memory.persistence: session_only` | Spec YAML (no persistent memory) |
| A004 | Protect IP & trade secrets | `data_sovereignty.tokenization` + `sentinel.pii_redaction` | Boundary audit logs showing zero restricted data crossings |
| A005 | Prevent cross-customer data exposure | `sentinel.auth.virtual_keys` (per-customer isolation) | LiteLLM key-scoped spend logs |
| A006 | Prevent PII leakage | `sentinel.pii_redaction` (Presidio) + `critic.guardrails.pii_output_scan` | Presidio redaction logs in traces |
| A007 | Prevent IP violations | `critic.guardrails.scope_check` | Guardrail evaluation traces |

### B. Security

| AIUC-1 Req | Requirement | STC Component | Evidence Source |
|-----------|------------|---------------|----------------|
| B - Adversarial robustness | MITRE ATLAS-informed testing | `adversarial/` (Garak testing scripts) | Quarterly test reports |
| B - Prompt injection prevention | Input guardrails | `critic.guardrails.input_rails.prompt_injection_detection` | NeMo Guardrails traces |
| B - Access controls | Per-persona auth with scoped permissions | `sentinel.auth.persona_keys` | LiteLLM access logs |

### C. Safety

| AIUC-1 Req | Requirement | STC Component | Evidence Source |
|-----------|------------|---------------|----------------|
| C001 | Define AI risk taxonomy | `risk_taxonomy` section in Declarative Spec | Spec YAML |
| C - Pre-deployment testing | Baseline evaluation suite | `reference-impl/evaluation/` | Evaluation reports (JSON) |
| C - Prevent harmful outputs | Output guardrails pipeline | `critic.guardrails.output_rails` | Phoenix traces per guardrail |
| C - Prevent out-of-scope outputs | Scope validator | `critic.guardrails.scope_check` | Guardrail traces |
| C - Flag high-risk outputs | Graduated escalation | `critic.escalation` | Escalation event logs |
| C - Third-party testing | Garak adversarial testing | `adversarial/` | Test reports |

### D. Reliability

| AIUC-1 Req | Requirement | STC Component | Evidence Source |
|-----------|------------|---------------|----------------|
| D - Predictable behavior | Trainer optimization with SLA thresholds | `trainer.maintenance_triggers` | Trainer performance reports |
| D - Error handling | Circuit breaker + graduated response | `critic.escalation.circuit_breaker` | Escalation traces |
| D - Recovery mechanisms | Maintenance mode with auto-retry | `trainer.maintenance_mode` | Trainer state logs |

### E. Accountability

| AIUC-1 Req | Requirement | STC Component | Evidence Source |
|-----------|------------|---------------|----------------|
| E - Transparency documentation | Declarative Specification (this IS the transparency doc) | `spec/stc-spec.yaml` | Versioned spec history |
| E - Audit trails | Immutable OTel traces across all personas | `audit.trace_backend` (Phoenix) | Exported Parquet files |
| E - Human oversight | Suspension requires human reset | `critic.escalation.suspension` | Escalation + reset logs |
| E - Prompt versioning | Langfuse prompt registry with trace linkage | `audit.prompt_registry` | Langfuse version history |

### F. Society

| AIUC-1 Req | Requirement | STC Component | Evidence Source |
|-----------|------------|---------------|----------------|
| F001 | Prevent AI cyber misuse | Input guardrails + prompt injection detection | NeMo Guardrails + adversarial test reports |
| F002 | Prevent catastrophic misuse | Scope restrictions + investment advice blocking | Guardrail configuration in spec + traces |

## Audit Workflow

For an AIUC-1 audit, the auditor would:

1. **Review the Declarative Specification** (`spec/stc-spec.yaml`) as the primary governance document
2. **Verify technical controls** by examining guardrail configurations and testing them
3. **Review audit trail exports** (Parquet files from Phoenix) for completeness and immutability
4. **Run the adversarial test suite** (`adversarial/`) and review quarterly test reports
5. **Verify data sovereignty** by examining boundary audit logs for any tier violations
6. **Confirm human oversight** by reviewing escalation events and resolution records
