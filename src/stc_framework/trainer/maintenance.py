"""Executes the spec's maintenance-mode action (degrade / pause / alert)."""

from __future__ import annotations

from typing import Any

from stc_framework.config.logging import get_logger
from stc_framework.resilience.degradation import (
    DegradationLevel,
    DegradationState,
    get_degradation_state,
)
from stc_framework.spec.models import STCSpec
from stc_framework.trainer.notifications import Notifier

_logger = get_logger(__name__)


class MaintenanceExecutor:
    def __init__(
        self,
        spec: STCSpec,
        *,
        notifier: Notifier | None = None,
        degradation: DegradationState | None = None,
    ) -> None:
        self._spec = spec
        self._notifier = notifier or Notifier()
        self._state = degradation or get_degradation_state()

    async def apply(self, report: dict[str, Any]) -> None:
        triggers = report.get("triggers") or []
        if not triggers:
            self._state.set(DegradationLevel.NORMAL, source="trainer.maintenance", reason="healthy")
            return

        mode = self._spec.trainer.maintenance_mode
        reason = f"triggers={','.join(triggers)}"

        if mode.action == "pause":
            self._state.set(DegradationLevel.PAUSED, source="trainer.maintenance", reason=reason)
        elif mode.action == "degrade":
            self._state.set(DegradationLevel.DEGRADED, source="trainer.maintenance", reason=reason)
        # "alert_only" — do not change state, just notify.

        message = f"Trainer maintenance triggered: {', '.join(triggers)}; action={mode.action}"
        for target in mode.notification:
            await self._notifier.alert(message, channel=target, context={"report": report})
