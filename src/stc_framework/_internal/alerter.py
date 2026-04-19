"""Threshold-based alert helper.

A common pattern across v0.3.0 subsystems: observe a metric (KRI value,
cost spend, request rate, honey-token access count) and emit GREEN /
AMBER / RED states with hysteresis. Each subsystem previously rolled its
own copy; this helper centralises the classification so audit payloads
and metric labels stay consistent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class AlertLevel(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"

    @property
    def numeric(self) -> int:
        return {AlertLevel.GREEN: 0, AlertLevel.AMBER: 1, AlertLevel.RED: 2}[self]


@dataclass(frozen=True)
class Thresholds:
    """Green / amber / red breakpoints for a single indicator.

    ``direction`` controls how ``value`` is compared:
      * ``"higher_is_worse"`` — typical for failure rates, latencies, costs.
      * ``"lower_is_worse"`` — typical for availability, success rates, budget remaining.

    Values between breakpoints map to GREEN; at-or-past ``amber`` maps to
    AMBER; at-or-past ``red`` maps to RED.
    """

    amber: float
    red: float
    direction: str = "higher_is_worse"

    def classify(self, value: float) -> AlertLevel:
        if self.direction == "higher_is_worse":
            if value >= self.red:
                return AlertLevel.RED
            if value >= self.amber:
                return AlertLevel.AMBER
            return AlertLevel.GREEN
        # lower_is_worse
        if value <= self.red:
            return AlertLevel.RED
        if value <= self.amber:
            return AlertLevel.AMBER
        return AlertLevel.GREEN


@dataclass
class AlertState:
    """Current level plus last observed value. Useful for dashboards."""

    level: AlertLevel
    value: float
    previous: AlertLevel | None = None

    @property
    def transitioned(self) -> bool:
        return self.previous is not None and self.previous != self.level


@dataclass
class ThresholdAlerter:
    """Stateful classifier: maintains the last level to detect transitions.

    Callers typically feed each new measurement and inspect ``transitioned``
    to decide whether to emit an audit event or page a human.
    """

    thresholds: Thresholds
    _last: AlertLevel = AlertLevel.GREEN

    def observe(self, value: float, on_transition: Callable[[AlertState], None] | None = None) -> AlertState:
        new_level = self.thresholds.classify(value)
        state = AlertState(level=new_level, value=value, previous=self._last)
        self._last = new_level
        if state.transitioned and on_transition is not None:
            on_transition(state)
        return state


__all__ = ["AlertLevel", "AlertState", "ThresholdAlerter", "Thresholds"]
