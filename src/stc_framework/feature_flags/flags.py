"""Typed feature-flag catalogue.

Every gated subsystem has:

* A :class:`FlagKey` enum member whose string value is the key the
  LaunchDarkly dashboard + API use.
* A hard-coded default in :data:`FLAG_DEFAULTS` — this is what the
  service does when the SDK cannot reach the relay AND there is no
  on-disk cache to fall back on. Defaults are deliberately
  conservative: disabled-by-default for any subsystem that alters
  behaviour in a production-visible way.

Changing a default is a breaking change (it may start enabling
subsystems in environments that previously defaulted them off).
Prefer flipping the LaunchDarkly dashboard instead.
"""

from __future__ import annotations

from enum import Enum


class FlagKey(str, Enum):
    """Feature-flag keys consumed by :class:`~stc_framework.feature_flags.client.LaunchDarklyClient`.

    Keys follow the ``stc.<subsystem>.<aspect>`` convention so
    operators can group them in the LaunchDarkly UI by prefix.
    """

    # --- v0.3.0 subsystem exposure ------------------------------------
    COMPLIANCE_ENABLED = "stc.compliance.enabled"
    THREAT_DETECTION_ENABLED = "stc.threat_detection.enabled"
    ORCHESTRATION_ENABLED = "stc.orchestration.enabled"
    RISK_OPTIMIZER_ENABLED = "stc.risk_optimizer.enabled"
    CATALOG_ENABLED = "stc.catalog.enabled"
    LINEAGE_ENABLED = "stc.lineage.enabled"

    # --- runtime incident companions to env-var invariants ------------
    # The env-var invariant is the authoritative source at startup; the
    # flag lets operators flip behaviour mid-incident without restart.
    TOKENIZATION_STRICT = "stc.tokenization.strict"
    AUDIT_WORM = "stc.audit.worm"

    # --- degradation policy -------------------------------------------
    DEGRADATION_AUTO_PAUSE = "stc.degradation.auto_pause"


# Hard-coded fallbacks. Conservative: every subsystem defaults off so a
# fresh deployment with no LD dashboard present does not silently turn
# on compliance blocking or threat-detection quarantine.
FLAG_DEFAULTS: dict[FlagKey, bool] = {
    FlagKey.COMPLIANCE_ENABLED: False,
    FlagKey.THREAT_DETECTION_ENABLED: False,
    FlagKey.ORCHESTRATION_ENABLED: False,
    FlagKey.RISK_OPTIMIZER_ENABLED: False,
    FlagKey.CATALOG_ENABLED: False,
    FlagKey.LINEAGE_ENABLED: False,
    FlagKey.TOKENIZATION_STRICT: True,
    FlagKey.AUDIT_WORM: True,
    FlagKey.DEGRADATION_AUTO_PAUSE: True,
}


__all__ = ["FLAG_DEFAULTS", "FlagKey"]
