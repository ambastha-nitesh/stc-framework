# experimental/

**Status: superseded. All code has been ported to `src/stc_framework/` in v0.3.0.**

This directory is an append-only archive. Do not import from it; do
not build on top of it. It remains only because git history is
load-bearing for code review and regulatory traceability.

## Status summary

| Module | v0.3.0 home |
|---|---|
| `critic/governance_engine.py` | `src/stc_framework/critic/` (split) |
| `spec/loader.py`, `stc-spec.yaml` | `src/stc_framework/spec/` + `spec-examples/` |
| `stalwart/financial_qa_agent.py` | `src/stc_framework/stalwart/` + `reference_impl/financial_qa/` |
| `sentinel/*` | `src/stc_framework/sentinel/*` |
| `trainer/optimization_manager.py` | `src/stc_framework/trainer/*` (split) |
| `adversarial/run_red_team.py` | `src/stc_framework/adversarial/` |
| `observability/*` | `src/stc_framework/observability/*` |
| `reference-impl/` | `src/stc_framework/reference_impl/` |
| `operational/retention_manager.py` | `src/stc_framework/governance/{retention,destruction}.py` |
| `operational/cost_controls.py` | `src/stc_framework/governance/{budget_controls,anomaly}.py` |
| `infrastructure/resilience.py` | `src/stc_framework/resilience/*` (already ported in v0.2.0) |
| `security/pen_testing.py` | `src/stc_framework/security/pen_testing.py` |
| `governance/data_catalog.py` | `src/stc_framework/governance/catalog.py` |
| `governance/data_lineage.py` | `src/stc_framework/governance/lineage.py` |
| `orchestration/workflow_engine.py` | `src/stc_framework/orchestration/{workflow,registry,simulation}.py` |
| `regulation/rule_2210.py` | `src/stc_framework/compliance/rule_2210.py` |
| `regulation/regulatory_ops.py` | `src/stc_framework/compliance/{reg_bi,nydfs_notification,part_500_cert}.py` |
| `regulation/ethical_legal.py` | `src/stc_framework/compliance/{bias_fairness,ip_risk,transparency,privilege_routing,fiduciary,legal_hold,explainability}.py` |
| `regulation/ai_sovereignty.py` | `src/stc_framework/compliance/sovereignty/{model_origin,query_pattern,state_law,jurisdiction}.py` |
| `risk/risk_register.py` | `src/stc_framework/risk/{register,kri}.py` |
| `risk/risk_adjusted_optimizer.py` | `src/stc_framework/risk/optimizer.py` |
| `security/threat_detection.py` | `src/stc_framework/security/threat_detection.py` |
| `infrastructure/perf_testing.py` | `src/stc_framework/infrastructure/perf_testing.py` |
| `infrastructure/session_state.py` | `src/stc_framework/infrastructure/session_state.py` |

## What to do if you were relying on `experimental/`

1. Find the v0.3.0 home in the table above.
2. Read the corresponding module's docstring — the public API has been
   tightened, renamed where ambiguous, and (where appropriate) split
   across multiple files.
3. Update imports. The rewrites are not drop-in — they use the v0.2.0
   primitives (audit chain, pluggable ``KeyValueStore``, async-first
   pipeline, typed error taxonomy) that the experimental code predates.

## Removal timeline

This directory is slated for deletion in **v0.4.0**. Ahead of that
release, we will verify there are no external references and no
regression in ported behaviour. Until then the tree stays read-only
for historical reference.
