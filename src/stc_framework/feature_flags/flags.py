"""AI Hub MVP feature-flag catalogue.

Scoped to exactly the 14 functional requirements from
``docs/ai-hub-prd.md``. Each flag gates one of the MVP enforcement
controls so operators can kill-switch a filter or cap in an incident
without a redeploy. The v0.3.0 subsystem-gating flags
(COMPLIANCE_ENABLED, THREAT_DETECTION_ENABLED, etc.) are explicitly
retired for the MVP release — they gated STC-framework subsystems
that the AI Hub MVP does not expose.

Every gated control has:

* A :class:`FlagKey` enum member whose string value is the key the
  LaunchDarkly dashboard + API use. Keys follow the
  ``aihub.<fr>.<aspect>`` convention so operators can group by FR.
* A hard-coded default in :data:`FLAG_DEFAULTS` — the last-resort
  fallback when the SDK cannot reach the relay AND there is no
  on-disk cache. Defaults are deliberately safety-first: every
  filter defaults ON so a total LD outage does not turn the
  guardrails off. Rate-limit / cap flags also default ON so a LD
  outage does not open the floodgates.

Changing a default is a breaking change; it alters the behaviour of
fresh deployments and of any deployment where the relay + cache are
both unavailable. Prefer flipping the LaunchDarkly dashboard instead.
"""

from __future__ import annotations

from enum import Enum


class FlagKey(str, Enum):
    """AI Hub MVP feature-flag keys.

    Mapping from FR to flag:

    * FR-3 — input filter chain: three flags, one per filter.
    * FR-5 — output filter chain: three flags, one per filter.
    * FR-9 — rate limits + spend cap: three flags (RPM, TPM, spend).
    * FR-10 — per-agent model allowlist: one enforcement flag.
    * FR-13 — audit ledger write: one kill-switch flag.
    """

    # --- FR-3 input filter chain (sequential, fail-closed, 300 ms ea) ----
    INPUT_FILTER_PROMPT_INJECTION = "aihub.input_filter.prompt_injection"
    INPUT_FILTER_PII = "aihub.input_filter.pii"
    INPUT_FILTER_CONTENT_POLICY = "aihub.input_filter.content_policy"

    # --- FR-5 output filter chain ----------------------------------------
    OUTPUT_FILTER_PII = "aihub.output_filter.pii"
    OUTPUT_FILTER_HARMFUL_CONTENT = "aihub.output_filter.harmful_content"
    OUTPUT_FILTER_POLICY_COMPLIANCE = "aihub.output_filter.policy_compliance"

    # --- FR-9 rate limits + spend cap ------------------------------------
    RATE_LIMIT_RPM_ENFORCEMENT = "aihub.rate_limit.rpm_enforcement"
    RATE_LIMIT_TPM_ENFORCEMENT = "aihub.rate_limit.tpm_enforcement"
    SPEND_CAP_ENFORCEMENT = "aihub.spend_cap.enforcement"

    # --- FR-10 per-agent model allowlist ---------------------------------
    MODEL_ALLOWLIST_ENFORCEMENT = "aihub.model_allowlist.enforcement"

    # --- FR-13 audit ledger kill-switch ----------------------------------
    # Turning this OFF downgrades the ledger to a best-effort local write
    # and returns success to callers. Intended for incident response
    # ONLY, and every flip is itself audit-logged upstream of the
    # ledger check. Defaults ON.
    AUDIT_LEDGER_WRITE = "aihub.audit.ledger_write"


# Hard-coded fallbacks. Every control defaults ON — a LaunchDarkly
# outage (relay down AND cache empty) must not open the guardrails or
# the rate-limit caps.
FLAG_DEFAULTS: dict[FlagKey, bool] = {
    FlagKey.INPUT_FILTER_PROMPT_INJECTION: True,
    FlagKey.INPUT_FILTER_PII: True,
    FlagKey.INPUT_FILTER_CONTENT_POLICY: True,
    FlagKey.OUTPUT_FILTER_PII: True,
    FlagKey.OUTPUT_FILTER_HARMFUL_CONTENT: True,
    FlagKey.OUTPUT_FILTER_POLICY_COMPLIANCE: True,
    FlagKey.RATE_LIMIT_RPM_ENFORCEMENT: True,
    FlagKey.RATE_LIMIT_TPM_ENFORCEMENT: True,
    FlagKey.SPEND_CAP_ENFORCEMENT: True,
    FlagKey.MODEL_ALLOWLIST_ENFORCEMENT: True,
    FlagKey.AUDIT_LEDGER_WRITE: True,
}


__all__ = ["FLAG_DEFAULTS", "FlagKey"]
