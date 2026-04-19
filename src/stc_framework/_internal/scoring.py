"""Weighted composite scoring utility.

Used by data catalog (quality dimensions), risk optimizer (accuracy + cost
+ risk), bias-fairness monitor (4/5ths rule), and any other module that
needs a transparent, validated weighted average.

Keeps the weighting formula in one place so auditors can reason about it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isclose


class ScoringError(ValueError):
    """Raised for weight / value validation failures."""


@dataclass
class WeightedScore:
    """A named weight + value pair used by :func:`weighted_average`.

    ``value`` is expected in ``[0, 1]`` for fractional scores (quality,
    risk) or any fixed scale as long as callers are consistent.
    """

    name: str
    weight: float
    value: float


def weighted_average(
    scores: list[WeightedScore],
    *,
    require_normalized_weights: bool = True,
) -> float:
    """Return ``sum(weight_i * value_i)``.

    Parameters
    ----------
    scores:
        Non-empty list of :class:`WeightedScore`.
    require_normalized_weights:
        If True (default) the weights must sum to 1.0 within a small
        tolerance. Turn this off only when intentionally using unnormalized
        weights (e.g. additive bias penalties).

    """
    if not scores:
        raise ScoringError("scores must be a non-empty list")
    total_weight = sum(s.weight for s in scores)
    if require_normalized_weights and not isclose(total_weight, 1.0, abs_tol=1e-6):
        raise ScoringError(f"weights must sum to 1.0; got {total_weight:.6f}")
    return sum(s.weight * s.value for s in scores)


def fairness_ratio(group_rate: float, reference_rate: float) -> float:
    """Return ``group_rate / reference_rate`` with the 4/5ths-rule semantics.

    The EEOC four-fifths rule: a selection/quality rate for any protected
    group less than 4/5 (0.80) of the rate for the reference group is
    evidence of adverse impact. Callers compare the returned ratio to
    0.80 to decide.
    """
    if reference_rate <= 0:
        raise ScoringError("reference_rate must be > 0 for a fairness ratio")
    return group_rate / reference_rate


def dimension_score(values: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Convenience wrapper: compute weighted average from two mappings.

    Raises :class:`ScoringError` if the key sets do not match exactly.
    """
    if set(values) != set(weights):
        missing = set(weights) - set(values)
        extra = set(values) - set(weights)
        raise ScoringError(f"value/weight key mismatch; missing={sorted(missing)} extra={sorted(extra)}")
    items = [WeightedScore(name=k, weight=weights[k], value=values[k]) for k in weights]
    return weighted_average(items)


__all__ = ["ScoringError", "WeightedScore", "dimension_score", "fairness_ratio", "weighted_average"]
