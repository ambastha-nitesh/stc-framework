# Feature flags — AI Hub MVP

The STC Framework uses LaunchDarkly to gate the MVP enforcement
controls from the AI Hub PRD (`docs/ai-hub-prd.md`). Every flag maps
to exactly one FR so operators can kill-switch a specific control in
an incident without a redeploy.

## Two-layer model

1. **Deploy-time gate** — the Dockerfile's `ARG DEPLOYED_SUBSYSTEMS`
   decides which `pyproject.toml` extras are installed into the image.
   A subsystem not in the extras list has no code in the image;
   LaunchDarkly cannot enable it.
2. **Runtime gate** — the Python SDK evaluates flags in
   `STCSystem.astart()` and on the request path. Only controls whose
   flag is on run.

Both gates must agree for a control to run. The deploy gate is the
hard boundary; LaunchDarkly is the soft boundary that lets operators
flip a control without a restart.

## Flag catalogue (MVP)

| FlagKey | LD key | Default | FR | Controls |
|---|---|---|---|---|
| `INPUT_FILTER_PROMPT_INJECTION` | `aihub.input_filter.prompt_injection` | `true` | FR-3 | Whether the prompt-injection filter runs in the input chain. Off = skip this filter (fail-open for this specific check). |
| `INPUT_FILTER_PII` | `aihub.input_filter.pii` | `true` | FR-3 | Whether the PII-input filter runs. |
| `INPUT_FILTER_CONTENT_POLICY` | `aihub.input_filter.content_policy` | `true` | FR-3 | Whether the content-policy input filter runs. |
| `OUTPUT_FILTER_PII` | `aihub.output_filter.pii` | `true` | FR-5 | Whether the PII-output scrub runs. |
| `OUTPUT_FILTER_HARMFUL_CONTENT` | `aihub.output_filter.harmful_content` | `true` | FR-5 | Whether the harmful-content filter runs. |
| `OUTPUT_FILTER_POLICY_COMPLIANCE` | `aihub.output_filter.policy_compliance` | `true` | FR-5 | Whether the policy-compliance output filter runs. |
| `RATE_LIMIT_RPM_ENFORCEMENT` | `aihub.rate_limit.rpm_enforcement` | `true` | FR-9 | Whether per-agent RPM is enforced. Off = allow all (emergency only). |
| `RATE_LIMIT_TPM_ENFORCEMENT` | `aihub.rate_limit.tpm_enforcement` | `true` | FR-9 | Whether per-agent TPM projection blocks requests. |
| `SPEND_CAP_ENFORCEMENT` | `aihub.spend_cap.enforcement` | `true` | FR-9 | Whether the domain monthly cap blocks requests. |
| `MODEL_ALLOWLIST_ENFORCEMENT` | `aihub.model_allowlist.enforcement` | `true` | FR-10 | Whether the per-agent model allowlist is checked. |
| `AUDIT_LEDGER_WRITE` | `aihub.audit.ledger_write` | `true` | FR-13 | Whether audit writes are required for request completion. Off = best-effort write, still return 200 to caller. **Use only during ledger incidents.** |

## Retired from MVP

The v0.3.0 subsystem-gating flags (`stc.compliance.enabled`,
`stc.threat_detection.enabled`, `stc.orchestration.enabled`,
`stc.risk_optimizer.enabled`, `stc.catalog.enabled`,
`stc.lineage.enabled`, `stc.tokenization.strict`, `stc.audit.worm`,
`stc.degradation.auto_pause`) are **not** part of the AI Hub MVP. Those
flags gated STC-framework subsystems that are not exposed by the MVP
release; they are retired from `FlagKey` to prevent confusion. If a
future release needs subsystem-level gating again, reintroduce them
with a bumped catalogue version.

## Fallback order

Evaluation order when `LaunchDarklyClient.variation()` fires:

1. If the SDK is initialised and the relay is reachable, return the LD
   decision.
2. If the relay is unreachable but the on-disk cache at
   `$STC_LD_CACHE_PATH` is populated, return the last cached decision.
3. Otherwise, return the hard default from `FLAG_DEFAULTS`.

Every step 2 / 3 fallback increments
`stc_feature_flag_fallback_total{flag}`. A sustained fallback rate
signals a relay outage — don't let it hide real flag changes.

All MVP defaults are `true`, so a complete LD outage (relay + cache
both empty) does NOT turn off any guardrail or cap. Safety first.

## Operator tasks

- **List flags + defaults**: `stc-governance flags list`
- **Evaluate a single flag**: `stc-governance flags eval --flag aihub.input_filter.prompt_injection`
- **Check SDK health**: `stc-governance flags status`
- **Flip a flag** without a deploy: LaunchDarkly dashboard →
  toggle → relay cache refreshes in ~1 s.

## Incident playbook

**Example 1 — the prompt-injection filter is returning false positives.**

1. LD dashboard → `aihub.input_filter.prompt_injection` → off.
2. Watch the false-positive rate fall.
3. Patch the filter. Re-enable. Reason for the flip goes into the LD
   dashboard's change log which is itself audit-logged.

**Example 2 — the audit ledger is down.**

This is the hardest decision. Flipping `aihub.audit.ledger_write`
off allows Bedrock calls to continue without audit records — the PRD
calls this out as a **conscious compliance decision**. Only Platform
Admin may flip it and every flip produces an entry in a non-audit
ops log. Re-enable as soon as the ledger recovers; the gap is
documented and reconciled via the daily integrity job.

## Adding a new flag

1. Add a new `FlagKey` member in
   `src/stc_framework/feature_flags/flags.py` + its default in
   `FLAG_DEFAULTS`.
2. Add the gate at the control's enforcement site (consult the flag
   via `LaunchDarklyClient.variation`).
3. Add a unit test in `tests/unit/test_feature_flags.py`.
4. Add the flag in the LaunchDarkly dashboard. Keep the dashboard
   default in sync with `FLAG_DEFAULTS` so fresh environments start
   in the intended state.
5. Document the flag in the table above.

Flag keys follow `aihub.<fr>.<aspect>` for MVP controls; the
convention is enforced by
`tests/unit/test_feature_flags.py::test_flag_key_string_format`.
