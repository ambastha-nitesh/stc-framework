"""Cost-anomaly detection.

Budgets catch expected overruns; anomalies catch *unexpected* ones:

* A pricing change doubles per-request cost overnight.
* A prompt regression causes the model to emit 10x more tokens.
* A jailbreak induces a single request to cost 50x the average.

We maintain a rolling average cost per (model, request-type) and raise
an alert when a new sample is ``N`` standard deviations (or a configured
multiplier) above the historical mean. Stateful, in-memory; callers feed
in the per-request cost after it is known.

Integrates with :class:`stc_framework._internal.alerter.ThresholdAlerter`
so GREEN / AMBER / RED transitions are emitted consistently with the
rest of the framework's dashboards.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from threading import RLock

from stc_framework._internal.alerter import AlertLevel, ThresholdAlerter, Thresholds


@dataclass
class AnomalyConfig:
    """Configuration for the rolling detector."""

    window_size: int = 100
    amber_multiplier: float = 3.0
    red_multiplier: float = 5.0
    min_samples: int = 20  # don't classify before we have this much history


@dataclass
class _ModelState:
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=100))
    alerter: ThresholdAlerter | None = None


@dataclass
class AnomalyObservation:
    """Result of a single :meth:`CostAnomalyDetector.observe` call."""

    cost_usd: float
    rolling_mean: float | None
    level: AlertLevel
    samples_seen: int
    transitioned: bool = False


class CostAnomalyDetector:
    """Per-model rolling-mean anomaly detector.

    Uses a fixed-size deque of the last ``window_size`` costs; the rolling
    mean is the classification baseline. ``amber`` and ``red`` thresholds
    are multiples of that mean.
    """

    def __init__(self, config: AnomalyConfig | None = None) -> None:
        self._cfg = config or AnomalyConfig()
        self._states: dict[str, _ModelState] = {}
        self._lock = RLock()

    def observe(self, model: str, cost_usd: float) -> AnomalyObservation:
        with self._lock:
            state = self._states.get(model)
            if state is None:
                state = _ModelState(samples=deque(maxlen=self._cfg.window_size))
                self._states[model] = state

            # Record BEFORE classifying so the rolling mean includes this sample;
            # matches how operators intuitively read "yesterday's average".
            state.samples.append(cost_usd)
            samples_seen = len(state.samples)

            if samples_seen < self._cfg.min_samples:
                return AnomalyObservation(
                    cost_usd=cost_usd,
                    rolling_mean=None,
                    level=AlertLevel.GREEN,
                    samples_seen=samples_seen,
                    transitioned=False,
                )

            mean = sum(state.samples) / samples_seen
            # Thresholds are multiples of the mean. Rebuild the alerter if
            # the baseline shifted materially (> 10%). Keeps hysteresis but
            # tracks genuine pricing changes over time.
            amber = mean * self._cfg.amber_multiplier
            red = mean * self._cfg.red_multiplier
            needs_rebuild = (
                state.alerter is None or abs(state.alerter.thresholds.amber - amber) / max(amber, 1e-6) > 0.1
            )
            if needs_rebuild:
                state.alerter = ThresholdAlerter(thresholds=Thresholds(amber=amber, red=red))

            assert state.alerter is not None
            transitioned_holder = {"t": False}

            def _on_tr(_state) -> None:  # type: ignore[no-untyped-def]
                transitioned_holder["t"] = True

            observation = state.alerter.observe(cost_usd, on_transition=_on_tr)
            return AnomalyObservation(
                cost_usd=cost_usd,
                rolling_mean=mean,
                level=observation.level,
                samples_seen=samples_seen,
                transitioned=transitioned_holder["t"],
            )

    def rolling_mean(self, model: str) -> float | None:
        state = self._states.get(model)
        if not state or not state.samples:
            return None
        return sum(state.samples) / len(state.samples)

    def reset(self, model: str) -> None:
        with self._lock:
            self._states.pop(model, None)


__all__ = ["AnomalyConfig", "AnomalyObservation", "CostAnomalyDetector"]
