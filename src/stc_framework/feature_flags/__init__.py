"""Runtime feature-flag gating via LaunchDarkly.

Flags evaluated here control which v0.3.0 subsystems initialise at
``STCSystem.astart()``. The complementary gate is the Dockerfile's
``DEPLOYED_SUBSYSTEMS`` build argument — LaunchDarkly can only enable
what was actually installed into the image.

Design goals:

* **Fail-open defaults**: every ``FlagKey`` has a hard-coded default so
  the service always boots, even when LaunchDarkly is unreachable and
  the on-disk cache is empty.
* **Visible degradation**: any LD evaluation that falls back to the
  default increments ``stc_feature_flag_fallback_total`` so the
  dashboards see it.
* **No import-time side effects**: constructing
  :class:`LaunchDarklyClient` never talks to the network. The SDK's
  streaming connection is initiated when the first ``variation`` call
  happens (LD SDK semantics).
"""

from stc_framework.feature_flags.client import LaunchDarklyClient
from stc_framework.feature_flags.flags import FLAG_DEFAULTS, FlagKey
from stc_framework.feature_flags.subsystem_registry import SubsystemRegistry

__all__ = [
    "FLAG_DEFAULTS",
    "FlagKey",
    "LaunchDarklyClient",
    "SubsystemRegistry",
]
