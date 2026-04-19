"""Cross-tier fiduciary fairness.

Watches for model-quality variance between account tiers (e.g. retail
vs. high-net-worth). A broker-dealer has a fiduciary duty to provide
equivalent quality of service regardless of account size; detecting
material variance surfaces a compliance flag.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TierUsage:
    model_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))


@dataclass
class FairnessCheckResult:
    tiers: list[str]
    share_by_tier: dict[str, dict[str, float]]
    concern: bool
    explanation: str


class FiduciaryFairnessChecker:
    """In-memory tracker of (tier, model) usage.

    Callers record a model usage per tier; :meth:`check_fairness`
    computes the per-tier share of each model. If two tiers' top models
    differ AND the gap exceeds ``material_gap_threshold`` (default 20%),
    the checker flags a concern.
    """

    def __init__(self, *, material_gap_threshold: float = 0.2) -> None:
        self._usage: dict[str, TierUsage] = defaultdict(TierUsage)
        self._gap = material_gap_threshold

    def record(self, *, tier: str, model: str) -> None:
        self._usage[tier].model_counts[model] += 1

    def check_fairness(self) -> FairnessCheckResult:
        if len(self._usage) < 2:
            return FairnessCheckResult(
                tiers=list(self._usage.keys()),
                share_by_tier={},
                concern=False,
                explanation="need at least two tiers to evaluate fairness",
            )
        share_by_tier: dict[str, dict[str, float]] = {}
        top_model: dict[str, str] = {}
        for tier, usage in self._usage.items():
            total = sum(usage.model_counts.values()) or 1
            shares = {m: c / total for m, c in usage.model_counts.items()}
            share_by_tier[tier] = shares
            top_model[tier] = max(shares, key=lambda k: shares[k]) if shares else ""
        distinct_tops = set(top_model.values())
        if len(distinct_tops) == 1:
            return FairnessCheckResult(
                tiers=list(self._usage.keys()),
                share_by_tier=share_by_tier,
                concern=False,
                explanation="all tiers share the same top model",
            )
        # Compute the gap in top model share across tiers.
        gaps: list[float] = []
        for tier_a, model_a in top_model.items():
            for tier_b in top_model:
                if tier_a == tier_b:
                    continue
                a = share_by_tier[tier_a].get(model_a, 0.0)
                b = share_by_tier[tier_b].get(model_a, 0.0)
                gaps.append(abs(a - b))
        max_gap = max(gaps, default=0.0)
        concern = max_gap >= self._gap
        return FairnessCheckResult(
            tiers=list(self._usage.keys()),
            share_by_tier=share_by_tier,
            concern=concern,
            explanation=(
                f"material top-model share gap {max_gap:.2%} exceeds threshold {self._gap:.0%}"
                if concern
                else f"max top-model share gap {max_gap:.2%} within tolerance"
            ),
        )

    def snapshot(self) -> dict[str, Any]:
        return {tier: dict(usage.model_counts) for tier, usage in self._usage.items()}


__all__ = ["FairnessCheckResult", "FiduciaryFairnessChecker"]
