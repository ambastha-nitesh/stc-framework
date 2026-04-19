# AIUC-1 Compliance Crosswalk

The example spec (`spec-examples/financial_qa.yaml`) contains an
explicit `compliance.aiuc_1` block that maps each control to the
framework component that enforces it.

| Area | Controls | Implementation |
|---|---|---|
| A. Data & Privacy | A001–A007 | `sentinel.redaction`, `sentinel.tokenization`, `sentinel.classifier`, `sentinel.auth` |
| B. Security | B_adversarial_robustness | `adversarial.runner` (quarterly) |
| C. Safety | C001, C_pre_deployment_testing, C_prevent_harmful_outputs | `spec.risk_taxonomy`, `reference_impl.scripts.run_baseline`, `critic.rails` |
| D. Reliability | D_predictable_behavior, D_error_handling | `trainer.optimizer`, `critic.escalation`, `resilience.*` |
| E. Accountability | E_transparency, E_audit_trail, E_human_oversight | spec itself, `observability.audit`, `critic.escalation` |
| F. Society | F001_prevent_misuse | `critic.validators.injection` |

## Evidence

Every boundary crossing, guardrail result, and escalation event is
written to the immutable audit log; exports are produced daily in either
JSONL or parquet. These logs are the audit evidence for the controls
above.

## Adversarial robustness

`stc-red-team` (or `stc_framework.adversarial.runner`) executes the
probe catalog and emits an AIUC-1-friendly report:

```json
{
  "aiuc_1_compliance": {
    "B_adversarial_robustness": true,
    "F001_prevent_misuse": true
  }
}
```
