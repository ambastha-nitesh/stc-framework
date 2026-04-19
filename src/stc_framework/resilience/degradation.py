"""Global degradation state machine.

Drives a single ``DegradationState`` per process. Listeners (Trainer's
``maintenance_triggers``, Critic's escalation) push transitions; the
``/readyz`` endpoint and gateway consult it.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from threading import RLock

from stc_framework.config.logging import get_logger
from stc_framework.observability.metrics import get_metrics

_logger = get_logger(__name__)


class DegradationLevel(enum.IntEnum):
    """Graduated operating modes."""

    NORMAL = 0
    DEGRADED = 1
    QUARANTINE = 2
    PAUSED = 3

    @classmethod
    def from_string(cls, value: str) -> DegradationLevel:
        mapping = {
            "normal": cls.NORMAL,
            "degraded": cls.DEGRADED,
            "quarantine": cls.QUARANTINE,
            "paused": cls.PAUSED,
            "suspension": cls.PAUSED,
        }
        return mapping.get(value.lower(), cls.NORMAL)


Listener = Callable[[DegradationLevel, DegradationLevel], None]


class DegradationState:
    """Thread-safe degradation state with pub-sub listeners."""

    def __init__(self) -> None:
        self._level = DegradationLevel.NORMAL
        self._lock = RLock()
        self._listeners: list[Listener] = []
        self._reasons: dict[str, str] = {}

    @property
    def level(self) -> DegradationLevel:
        with self._lock:
            return self._level

    def is_paused(self) -> bool:
        return self.level >= DegradationLevel.PAUSED

    def allow_traffic(self) -> bool:
        return self.level < DegradationLevel.PAUSED

    def subscribe(self, listener: Listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def set(self, level: DegradationLevel, *, source: str, reason: str = "") -> None:
        """Transition to ``level`` if it's worse than the current level, or
        explicitly clear by passing :data:`DegradationLevel.NORMAL`.
        """
        with self._lock:
            previous = self._level
            if level != previous:
                self._level = level
                if level == DegradationLevel.NORMAL:
                    self._reasons.pop(source, None)
                else:
                    self._reasons[source] = reason
                get_metrics().escalation_level.set(int(level))
                _logger.warning(
                    "degradation.transition",
                    from_level=previous.name,
                    to_level=level.name,
                    source=source,
                    reason=reason,
                )
                for listener in list(self._listeners):
                    try:
                        listener(previous, level)
                    except Exception:  # pragma: no cover
                        _logger.exception("degradation.listener_error")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "level": self._level.name,
                "reasons": dict(self._reasons),
            }


_STATE: DegradationState | None = None
_STATE_LOCK = RLock()


def get_degradation_state() -> DegradationState:
    global _STATE
    with _STATE_LOCK:
        if _STATE is None:
            _STATE = DegradationState()
        return _STATE


def reset_degradation_for_tests() -> None:
    global _STATE
    with _STATE_LOCK:
        _STATE = None
