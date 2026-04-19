"""Best-effort metric emission with visibility.

Rationale: every v0.3.0 module that publishes a Prometheus metric was
wrapping the call in ``try / except Exception: pass``. That pattern
hides real label-name / shape bugs — a dev who passes the wrong
labels gets silent no-ops in prod and never discovers it.

These helpers narrow the catch to the exception classes
``prometheus_client`` raises for mismatched labels (``ValueError``)
and log the failure at WARNING so the mistake is visible in logs
and discoverable in tests. Other exception classes (e.g. a genuine
Prometheus registry failure) still propagate — we are NOT silencing
them.
"""

from __future__ import annotations

from typing import Any

from stc_framework.config.logging import get_logger

_logger = get_logger(__name__)


def safe_inc(metric: Any, *, amount: float = 1.0, **labels: Any) -> None:
    """``metric.labels(**labels).inc(amount)`` with visible failure.

    ``labels`` may be empty for unlabelled counters.
    """
    try:
        target = metric.labels(**labels) if labels else metric
        target.inc(amount)
    except ValueError as exc:
        _logger.warning(
            "metrics.label_mismatch",
            metric=getattr(metric, "_name", repr(metric)),
            labels=labels,
            error=str(exc),
        )
    except AttributeError as exc:
        # Metric wasn't initialised (tests that reset the registry mid-run).
        _logger.warning(
            "metrics.uninitialised",
            metric=repr(metric),
            error=str(exc),
        )


def safe_set(metric: Any, value: float, **labels: Any) -> None:
    """``metric.labels(**labels).set(value)`` with visible failure."""
    try:
        target = metric.labels(**labels) if labels else metric
        target.set(value)
    except ValueError as exc:
        _logger.warning(
            "metrics.label_mismatch",
            metric=getattr(metric, "_name", repr(metric)),
            labels=labels,
            error=str(exc),
        )
    except AttributeError as exc:
        _logger.warning("metrics.uninitialised", metric=repr(metric), error=str(exc))


def safe_observe(metric: Any, value: float, **labels: Any) -> None:
    """``metric.labels(**labels).observe(value)`` for histograms."""
    try:
        target = metric.labels(**labels) if labels else metric
        target.observe(value)
    except ValueError as exc:
        _logger.warning(
            "metrics.label_mismatch",
            metric=getattr(metric, "_name", repr(metric)),
            labels=labels,
            error=str(exc),
        )
    except AttributeError as exc:
        _logger.warning("metrics.uninitialised", metric=repr(metric), error=str(exc))


__all__ = ["safe_inc", "safe_observe", "safe_set"]
