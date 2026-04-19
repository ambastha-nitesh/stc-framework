"""Escalation state machine with consecutive-failure circuit breaker.

Wraps the original count-based thresholds with:
- a per-process failure window (time-bounded),
- a consecutive-failure counter that trips the Critic circuit breaker
  (``escalation.circuit_breaker`` in the spec),
- transitions wired to :class:`DegradationState` so the rest of the
  system (readiness probes, Trainer, Sentinel) can react.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock

from stc_framework.config.logging import get_logger
from stc_framework.critic.validators.base import GovernanceVerdict
from stc_framework.observability.metrics import get_metrics
from stc_framework.resilience.degradation import (
    DegradationLevel,
    DegradationState,
    get_degradation_state,
)
from stc_framework.spec.models import EscalationSpec

_logger = get_logger(__name__)


@dataclass
class _WindowEntry:
    timestamp: datetime
    critical_failures: int


class EscalationManager:
    """Tracks failures and graduates the operating mode."""

    def __init__(
        self,
        spec: EscalationSpec,
        *,
        window_size: int = 10,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        degradation_state: DegradationState | None = None,
    ) -> None:
        self._spec = spec
        self._clock = clock
        self._state = degradation_state or get_degradation_state()
        self._window: deque[_WindowEntry] = deque(maxlen=window_size)
        self._consecutive_failures = 0
        self._last_trip: datetime | None = None
        self._lock = RLock()

    @property
    def current_level(self) -> str | None:
        lvl = self._state.level
        if lvl == DegradationLevel.NORMAL:
            return None
        return lvl.name.lower()

    def record_result(self, verdict: GovernanceVerdict) -> None:
        """Record a verdict and maybe escalate."""
        with self._lock:
            critical_fails = sum(1 for r in verdict.results if not r.passed and r.severity == "critical")
            self._window.append(
                _WindowEntry(
                    timestamp=self._clock(),
                    critical_failures=critical_fails,
                )
            )
            if critical_fails > 0:
                self._consecutive_failures += 1
            else:
                self._consecutive_failures = 0

            if critical_fails > 0:
                get_metrics().guardrail_failures_total.labels(rail="__any__", severity="critical").inc(critical_fails)

            self._maybe_escalate()

    def _maybe_escalate(self) -> None:
        cb = self._spec.circuit_breaker
        now = self._clock()

        # Parse "3 consecutive failures" from the trigger string.
        try:
            threshold = int(cb.trigger.split()[0])
        except (ValueError, IndexError):
            threshold = 3

        total_crit = sum(e.critical_failures for e in self._window)

        target_level: DegradationLevel = DegradationLevel.NORMAL
        if self._consecutive_failures >= threshold or total_crit >= 5:
            target_level = DegradationLevel.PAUSED
        elif total_crit >= 3:
            target_level = DegradationLevel.QUARANTINE
        elif total_crit >= 2:
            target_level = DegradationLevel.DEGRADED

        # Cooldown only governs *recovery* (dropping level), never escalation.
        if target_level < self._state.level:
            if cb.cooldown_seconds and self._last_trip is not None:
                if now - self._last_trip < timedelta(seconds=cb.cooldown_seconds):
                    return
                if not cb.auto_retry:
                    return
                _logger.info("escalation.cooldown_elapsed")
                self._consecutive_failures = 0
                self._last_trip = None
                # Clear the failure window so the system returns to NORMAL
                # after a full cooldown, not just one level.
                self._window.clear()
                target_level = DegradationLevel.NORMAL

        if target_level != self._state.level:
            if target_level > self._state.level:
                self._last_trip = now
            self._state.set(
                target_level,
                source="critic.escalation",
                reason=(f"consecutive={self._consecutive_failures}, " f"window_critical={total_crit}"),
            )
