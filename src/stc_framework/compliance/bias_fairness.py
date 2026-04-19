"""Bias & fairness monitor — disparate-impact detection.

Tracks per-demographic-group response quality and computes the 4/5ths
rule (EEOC) ratio between any protected group and the reference group.
A ratio below 0.80 is evidence of adverse impact and escalates a bias
alert.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from stc_framework._internal.scoring import ScoringError, fairness_ratio
from stc_framework.governance.events import AuditEvent
from stc_framework.observability.audit import AuditLogger, AuditRecord

ADVERSE_IMPACT_RATIO = 0.80


@dataclass
class FairnessMetric:
    group: str
    reference_group: str
    group_rate: float
    reference_rate: float
    ratio: float
    adverse_impact: bool


@dataclass
class BiasReport:
    reference_group: str
    per_group: dict[str, float] = field(default_factory=dict)
    findings: list[FairnessMetric] = field(default_factory=list)


class BiasFairnessMonitor:
    """In-memory, per-deployment fairness tracker.

    Callers feed per-request quality scores (0..1) keyed by demographic
    group. ``evaluate_fairness`` picks a reference group (or caller-named)
    and reports disparate impact against every other group.
    """

    def __init__(self, *, audit: AuditLogger | None = None) -> None:
        self._audit = audit
        self._scores: dict[str, list[float]] = defaultdict(list)

    def record_response_quality(self, *, group: str, score: float) -> None:
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be in [0.0, 1.0]")
        self._scores[group].append(score)

    async def evaluate_fairness(self, *, reference_group: str | None = None) -> BiasReport:
        if not self._scores:
            return BiasReport(reference_group=reference_group or "")

        per_group = {g: mean(scores) if scores else 0.0 for g, scores in self._scores.items()}
        ref = reference_group or max(per_group, key=lambda k: per_group[k])
        ref_rate = per_group[ref]
        findings: list[FairnessMetric] = []
        for group, rate in per_group.items():
            if group == ref:
                continue
            try:
                ratio = fairness_ratio(rate, ref_rate)
            except ScoringError:
                continue
            adverse = ratio < ADVERSE_IMPACT_RATIO
            findings.append(
                FairnessMetric(
                    group=group,
                    reference_group=ref,
                    group_rate=rate,
                    reference_rate=ref_rate,
                    ratio=ratio,
                    adverse_impact=adverse,
                )
            )
            if adverse and self._audit is not None:
                await self._audit.emit(
                    AuditRecord(
                        event_type=AuditEvent.COMPLIANCE_VIOLATION.value,
                        persona="compliance",
                        extra={
                            "rule": "bias_fairness",
                            "group": group,
                            "reference_group": ref,
                            "ratio": round(ratio, 4),
                            "adverse_impact": True,
                        },
                    )
                )
        return BiasReport(reference_group=ref, per_group=per_group, findings=findings)

    def reset(self) -> None:
        self._scores.clear()

    def snapshot(self) -> dict[str, Any]:
        return {g: mean(scores) if scores else 0.0 for g, scores in self._scores.items()}


__all__ = [
    "ADVERSE_IMPACT_RATIO",
    "BiasFairnessMonitor",
    "BiasReport",
    "FairnessMetric",
]
