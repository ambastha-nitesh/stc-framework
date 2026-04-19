"""Evaluate the subsystem-gating flag bundle in one call.

A single ``SubsystemRegistry.evaluate(settings)`` returns the full map
of ``FlagKey -> bool`` needed by ``STCSystem.astart()`` to decide which
subsystems warm up. Extracting this into its own class keeps the LD SDK
import surface narrow and makes the tests straightforward — fake the
client, assert the registry's behaviour independently.
"""

from __future__ import annotations

from typing import Any

from stc_framework.config.settings import STCSettings
from stc_framework.feature_flags.client import LaunchDarklyClient
from stc_framework.feature_flags.flags import FLAG_DEFAULTS, FlagKey


class SubsystemRegistry:
    """Owns one LaunchDarkly context and evaluates every flag once per boot."""

    def __init__(self, client: LaunchDarklyClient) -> None:
        self._client = client
        self._state: dict[FlagKey, bool] = {}

    def _build_context(self, settings: STCSettings, deployed_subsystems: list[str]) -> Any:
        """Build the LD evaluation context for the service as a whole.

        The LD SDK import is done lazily so a deployment that opted out
        of the ``launchdarkly`` extra still imports this module (useful
        for type checking + CLI tools).
        """
        try:
            from ldclient import Context
        except ImportError:
            # Caller will hit the same ImportError inside the client.
            return {
                "kind": "service",
                "key": settings.service_name,
                "env": settings.env,
                "version": settings.service_version,
                "deployed_subsystems": deployed_subsystems,
            }
        builder = Context.builder(settings.service_name).kind("service")
        builder.set("env", settings.env)
        builder.set("version", settings.service_version)
        builder.set("deployed_subsystems", deployed_subsystems)
        return builder.build()

    def evaluate(
        self,
        settings: STCSettings,
        *,
        deployed_subsystems: list[str] | None = None,
    ) -> dict[FlagKey, bool]:
        """Evaluate every :class:`FlagKey`; cache the result.

        ``deployed_subsystems`` is an informational attribute passed to
        the LD context (not a gate in itself — the Dockerfile controls
        that). Callers typically pass the value of the
        ``DEPLOYED_SUBSYSTEMS`` build argument, read from a label on
        the running container at process start.
        """
        context = self._build_context(settings, deployed_subsystems or [])
        evaluated: dict[FlagKey, bool] = {}
        for flag in FlagKey:
            evaluated[flag] = self._client.variation(flag, context, FLAG_DEFAULTS[flag])
        self._state = evaluated
        return evaluated

    def should_initialize(self, flag: FlagKey) -> bool:
        """Return the cached evaluation. :meth:`evaluate` must have run first."""
        if flag not in self._state:
            # Boot-sequence mistake: log and fail-open to the hard default.
            return FLAG_DEFAULTS[flag]
        return self._state[flag]

    @property
    def state(self) -> dict[FlagKey, bool]:
        return dict(self._state)


__all__ = ["SubsystemRegistry"]
