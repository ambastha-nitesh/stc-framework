"""Risk-adjusted optimizer — veto layer on Trainer decisions.

The Trainer naturally picks whatever candidate maximises (accuracy,
cost) for the current workload. The optimizer intercepts that choice
and runs four independent evaluators:

1. **Provenance** — reject models with ``origin_risk`` outside the
   operator-declared allow-list (e.g. restrict restricted-tier traffic
   to trusted-origin models only).
2. **Sovereignty** — reject candidates whose routing would cross a
   disallowed jurisdiction boundary.
3. **Vendor concentration** — reject candidates that would push a
   single vendor's share past ``max_vendor_share`` (75% by default).
4. **KRI status** — reject any candidate if a linked KRI is RED and
   ``veto_on_kri_red`` is set.

Surviving candidates are scored composite = accuracy · w_a + cost · w_c +
(1-risk) · w_r. Ties broken by lower risk then lower cost.

If every candidate is vetoed the optimizer raises
:class:`RiskOptimizerVeto` — callers handle this at the degradation
level (fall back to v0.2.0 routing, flip to degraded mode, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stc_framework._internal.scoring import WeightedScore, weighted_average
from stc_framework.errors import RiskOptimizerVeto
from stc_framework.governance.events import AuditEvent
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.risk.kri import KRIEngine, KRIStatus


class VetoReason(str, Enum):
    PROVENANCE_UNTRUSTED = "provenance_untrusted"
    SOVEREIGNTY_VIOLATION = "sovereignty_violation"
    CONCENTRATION_RISK = "concentration_risk"
    KRI_RED = "kri_red"


@dataclass
class RiskAssessment:
    risk_score: float = 0.0  # 0.0 = safe, 1.0 = maximum risk
    vetoed: bool = False
    veto_reasons: list[VetoReason] = field(default_factory=list)
    factors: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class OptimizationCandidate:
    """A single option the optimizer is asked to rank."""

    candidate_id: str
    description: str = ""
    accuracy_score: float = 0.5  # 0..1
    cost_score: float = 0.5  # 0..1, higher=cheaper
    metadata: dict[str, Any] = field(default_factory=dict)
    # Filled by the optimizer:
    risk_assessment: RiskAssessment | None = None
    composite_score: float = 0.0


@dataclass
class OptimizationDecision:
    """Full audit-friendly record of one optimizer run."""

    decision_type: str
    data_tier: str
    selected: OptimizationCandidate | None
    candidates: list[OptimizationCandidate]
    decision_reason: str = ""
    risk_override: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------- evaluators ---------------------------------------------------


@dataclass
class ProvenanceEvaluator:
    """Check model provenance against declared allow-list."""

    allowed_origin_risks: set[str]  # e.g. {"trusted", "cautious"}

    def evaluate(self, candidate: OptimizationCandidate) -> tuple[float, VetoReason | None]:
        origin = str(candidate.metadata.get("origin_risk", "trusted")).lower()
        if origin not in self.allowed_origin_risks:
            return 1.0, VetoReason.PROVENANCE_UNTRUSTED
        # Quantify: trusted=0, cautious=0.3, restricted=0.6, sanctioned=1.0
        scale = {"trusted": 0.0, "cautious": 0.3, "restricted": 0.6, "sanctioned": 1.0}
        return scale.get(origin, 0.5), None


@dataclass
class SovereigntyEvaluator:
    """Enforce routing jurisdiction for each data tier."""

    allowed_jurisdictions: set[str]  # e.g. {"US", "EU"}
    tier_policy: dict[str, set[str]] = field(default_factory=dict)  # optional per-tier override

    def evaluate(
        self,
        candidate: OptimizationCandidate,
        *,
        data_tier: str,
    ) -> tuple[float, VetoReason | None]:
        jurisdiction = str(candidate.metadata.get("jurisdiction", "US")).upper()
        allowed = self.tier_policy.get(data_tier, self.allowed_jurisdictions)
        if jurisdiction not in allowed:
            return 1.0, VetoReason.SOVEREIGNTY_VIOLATION
        return 0.0, None


@dataclass
class ConcentrationEvaluator:
    """Prevent any single vendor/provider from growing past ``max_share``."""

    max_share: float = 0.75
    current_shares: dict[str, float] = field(default_factory=dict)

    def evaluate(self, candidate: OptimizationCandidate) -> tuple[float, VetoReason | None]:
        vendor = str(candidate.metadata.get("vendor", "")).lower()
        if not vendor:
            return 0.0, None
        share = self.current_shares.get(vendor, 0.0)
        if share > self.max_share:
            return 1.0, VetoReason.CONCENTRATION_RISK
        # Risk contribution scales linearly as we approach the ceiling.
        return max(0.0, share / self.max_share), None


@dataclass
class KRIEvaluator:
    """Reject candidates linked to RED KRIs."""

    kri_engine: KRIEngine
    veto_on_red: bool = True

    async def evaluate(self, candidate: OptimizationCandidate) -> tuple[float, VetoReason | None]:
        linked = list(candidate.metadata.get("linked_kris", []))
        if not linked:
            return 0.0, None
        worst = KRIStatus.GREEN
        for kri_id in linked:
            latest = await self.kri_engine.latest(kri_id)
            if latest is None:
                continue
            if latest.status.numeric > worst.numeric:
                worst = latest.status
        if worst is KRIStatus.RED and self.veto_on_red:
            return 1.0, VetoReason.KRI_RED
        return {KRIStatus.GREEN: 0.0, KRIStatus.AMBER: 0.5, KRIStatus.RED: 1.0}[worst], None


# ---------- optimizer ----------------------------------------------------


@dataclass
class OptimizerConfig:
    accuracy_weight: float = 0.4
    cost_weight: float = 0.2
    risk_weight: float = 0.4  # higher = more risk-averse


class RiskAdjustedOptimizer:
    """Full optimizer over a list of :class:`OptimizationCandidate`."""

    def __init__(
        self,
        *,
        provenance: ProvenanceEvaluator,
        sovereignty: SovereigntyEvaluator,
        concentration: ConcentrationEvaluator,
        kri: KRIEvaluator | None = None,
        config: OptimizerConfig | None = None,
        audit: AuditLogger | None = None,
    ) -> None:
        self._provenance = provenance
        self._sovereignty = sovereignty
        self._concentration = concentration
        self._kri = kri
        self._config = config or OptimizerConfig()
        self._audit = audit

    async def optimize(
        self,
        decision_type: str,
        candidates: list[OptimizationCandidate],
        *,
        data_tier: str = "public",
    ) -> OptimizationDecision:
        if not candidates:
            raise RiskOptimizerVeto(message="no candidates supplied to optimizer")

        # Score each candidate; record veto reasons.
        for cand in candidates:
            cand.risk_assessment = await self._assess(cand, data_tier=data_tier)
            if cand.risk_assessment.vetoed:
                cand.composite_score = -1.0  # sentinel: never selectable
            else:
                cand.composite_score = weighted_average(
                    [
                        WeightedScore(name="accuracy", weight=self._config.accuracy_weight, value=cand.accuracy_score),
                        WeightedScore(name="cost", weight=self._config.cost_weight, value=cand.cost_score),
                        WeightedScore(
                            name="safety",
                            weight=self._config.risk_weight,
                            value=1.0 - cand.risk_assessment.risk_score,
                        ),
                    ]
                )

        survivors = [c for c in candidates if c.risk_assessment is not None and not c.risk_assessment.vetoed]
        if not survivors:
            decision = OptimizationDecision(
                decision_type=decision_type,
                data_tier=data_tier,
                selected=None,
                candidates=candidates,
                decision_reason="all candidates vetoed",
                risk_override=True,
            )
            await self._emit_audit(decision, event=AuditEvent.OPTIMIZER_VETO)
            raise RiskOptimizerVeto(
                message=f"{decision_type}: all candidates vetoed",
                context={
                    "reasons": [
                        [r.value for r in (c.risk_assessment.veto_reasons if c.risk_assessment else [])]
                        for c in candidates
                    ],
                },
            )

        # Sort: highest composite, tie-break by lower risk, then lower cost penalty.
        survivors.sort(
            key=lambda c: (
                -c.composite_score,
                c.risk_assessment.risk_score if c.risk_assessment else 1.0,
                -c.cost_score,
            )
        )
        selected = survivors[0]
        decision = OptimizationDecision(
            decision_type=decision_type,
            data_tier=data_tier,
            selected=selected,
            candidates=candidates,
            decision_reason=f"composite={selected.composite_score:.4f}",
        )
        await self._emit_audit(decision, event=AuditEvent.OPTIMIZER_DECISION)
        return decision

    async def _assess(self, candidate: OptimizationCandidate, *, data_tier: str) -> RiskAssessment:
        assessment = RiskAssessment()
        prov_score, prov_veto = self._provenance.evaluate(candidate)
        assessment.factors["provenance"] = prov_score
        if prov_veto is not None:
            assessment.vetoed = True
            assessment.veto_reasons.append(prov_veto)
        sov_score, sov_veto = self._sovereignty.evaluate(candidate, data_tier=data_tier)
        assessment.factors["sovereignty"] = sov_score
        if sov_veto is not None:
            assessment.vetoed = True
            assessment.veto_reasons.append(sov_veto)
        con_score, con_veto = self._concentration.evaluate(candidate)
        assessment.factors["concentration"] = con_score
        if con_veto is not None:
            assessment.vetoed = True
            assessment.veto_reasons.append(con_veto)
        if self._kri is not None:
            kri_score, kri_veto = await self._kri.evaluate(candidate)
            assessment.factors["kri"] = kri_score
            if kri_veto is not None:
                assessment.vetoed = True
                assessment.veto_reasons.append(kri_veto)
        # Overall risk = max of factors — worst-of is the honest aggregation
        # for veto-style scoring (any dominant factor dominates).
        assessment.risk_score = max(assessment.factors.values(), default=0.0)
        return assessment

    async def _emit_audit(self, decision: OptimizationDecision, *, event: AuditEvent) -> None:
        if self._audit is None:
            return
        await self._audit.emit(
            AuditRecord(
                event_type=event.value,
                persona="risk",
                extra={
                    "decision_type": decision.decision_type,
                    "data_tier": decision.data_tier,
                    "selected": decision.selected.candidate_id if decision.selected else None,
                    "reason": decision.decision_reason,
                    "risk_override": decision.risk_override,
                    "candidate_count": len(decision.candidates),
                },
            )
        )


__all__ = [
    "ConcentrationEvaluator",
    "KRIEvaluator",
    "OptimizationCandidate",
    "OptimizationDecision",
    "OptimizerConfig",
    "ProvenanceEvaluator",
    "RiskAdjustedOptimizer",
    "RiskAssessment",
    "SovereigntyEvaluator",
    "VetoReason",
]
