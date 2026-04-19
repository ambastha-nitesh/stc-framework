"""
STC Framework — Risk-Adjusted Optimizer
risk/risk_adjusted_optimizer.py

Injects risk awareness into the Trainer's optimization decisions.
Every Trainer decision (model selection, provider routing, prompt
modification) passes through a risk filter that can veto, adjust,
or flag decisions that would increase risk exposure.

Risk weights from the ERM framework (Section 8.1) are enforced here.
The optimizer computes a composite score: accuracy * w_a + cost * w_c + risk * w_r
where risk factors can veto a decision even if accuracy and cost are optimal.

Integrates with:
  - Risk Register (risk scores for linked risks)
  - KRI Engine (current indicator status)
  - Model Provenance (trust levels)
  - Data Classification (sovereignty constraints)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stc.risk.optimizer")


# ── Risk Weights ────────────────────────────────────────────────────────────

@dataclass
class RiskWeights:
    """Risk weights for different optimization decisions."""
    accuracy: float = 0.40
    cost: float = 0.20
    risk: float = 0.40

    def validate(self):
        total = self.accuracy + self.cost + self.risk
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Weights must sum to 1.0, got {total}")


DECISION_WEIGHTS = {
    "model_selection": RiskWeights(0.40, 0.20, 0.40),
    "provider_routing": RiskWeights(0.30, 0.30, 0.40),
    "prompt_modification": RiskWeights(0.50, 0.10, 0.40),
    "context_window": RiskWeights(0.40, 0.30, 0.30),
    "fallback_activation": RiskWeights(0.20, 0.10, 0.70),
}


# ── Risk Factors ────────────────────────────────────────────────────────────

class VetoReason(Enum):
    """Reasons a risk veto can be issued."""
    PROVENANCE_UNTRUSTED = "Model provenance trust level insufficient"
    SOVEREIGNTY_VIOLATION = "Would violate data sovereignty tier"
    APPETITE_BREACH = "Would exceed risk appetite threshold"
    KRI_RED = "Linked KRI is in RED status"
    SAFETY_UNVALIDATED = "Model has not passed safety evaluation"
    CONCENTRATION_RISK = "Would exceed vendor concentration limit"


@dataclass
class RiskAssessment:
    """Risk assessment for a candidate decision."""
    risk_score: float           # 0.0 (no risk) to 1.0 (maximum risk)
    factors: List[Dict[str, Any]]
    vetoed: bool = False
    veto_reasons: List[VetoReason] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class OptimizationCandidate:
    """A candidate option for an optimization decision."""
    candidate_id: str
    description: str
    accuracy_score: float       # 0.0 to 1.0
    cost_score: float           # 0.0 (cheapest) to 1.0 (most expensive)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Filled by optimizer
    risk_assessment: Optional[RiskAssessment] = None
    composite_score: float = 0.0


@dataclass
class OptimizationDecision:
    """The result of a risk-adjusted optimization."""
    decision_type: str
    selected: Optional[OptimizationCandidate]
    candidates: List[OptimizationCandidate]
    decision_reason: str
    risk_override: bool = False      # True if risk vetoed the accuracy-optimal choice
    timestamp: str = ""


# ── Risk Factor Evaluators ──────────────────────────────────────────────────

class ModelProvenanceEvaluator:
    """Evaluates risk based on model provenance trust level."""

    TRUST_SCORES = {
        "verified": 0.0,     # No risk
        "trusted": 0.1,      # Minimal risk
        "unverified": 0.6,   # Significant risk
        "suspicious": 1.0,   # Maximum risk — veto
        "blocked": 1.0,      # Veto
    }

    def evaluate(self, candidate: OptimizationCandidate) -> Dict[str, Any]:
        trust = candidate.metadata.get("provenance_trust", "unverified")
        score = self.TRUST_SCORES.get(trust, 0.8)
        veto = trust in ("suspicious", "blocked")
        return {
            "factor": "model_provenance",
            "trust_level": trust,
            "risk_score": score,
            "veto": veto,
            "veto_reason": VetoReason.PROVENANCE_UNTRUSTED if veto else None,
        }


class DataSovereigntyEvaluator:
    """Evaluates risk based on data sovereignty compliance."""

    def evaluate(self, candidate: OptimizationCandidate, data_tier: str = "public") -> Dict[str, Any]:
        provider_type = candidate.metadata.get("provider_type", "external")
        provider_tiers = candidate.metadata.get("allowed_tiers", ["public"])

        compliant = data_tier in provider_tiers
        if not compliant and data_tier in ("restricted", "internal"):
            return {
                "factor": "data_sovereignty",
                "data_tier": data_tier,
                "provider_type": provider_type,
                "risk_score": 1.0,
                "veto": True,
                "veto_reason": VetoReason.SOVEREIGNTY_VIOLATION,
            }

        risk_map = {"local": 0.0, "vpc": 0.1, "external": 0.3}
        return {
            "factor": "data_sovereignty",
            "data_tier": data_tier,
            "provider_type": provider_type,
            "risk_score": risk_map.get(provider_type, 0.5),
            "veto": False,
            "veto_reason": None,
        }


class VendorConcentrationEvaluator:
    """Evaluates vendor concentration risk."""

    def __init__(self, max_concentration: float = 0.70):
        self.max_concentration = max_concentration
        self._provider_usage: Dict[str, int] = {}
        self._total_requests = 0

    def record_usage(self, provider: str):
        self._provider_usage[provider] = self._provider_usage.get(provider, 0) + 1
        self._total_requests += 1

    def evaluate(self, candidate: OptimizationCandidate) -> Dict[str, Any]:
        provider = candidate.metadata.get("provider", "unknown")
        if self._total_requests == 0:
            return {"factor": "vendor_concentration", "risk_score": 0.0, "veto": False, "veto_reason": None}

        current_share = self._provider_usage.get(provider, 0) / self._total_requests
        would_be_share = (self._provider_usage.get(provider, 0) + 1) / (self._total_requests + 1)

        veto = would_be_share > self.max_concentration + 0.10  # Hard veto at 80%
        risk_score = min(1.0, would_be_share / self.max_concentration)

        return {
            "factor": "vendor_concentration",
            "provider": provider,
            "current_share": round(current_share, 3),
            "projected_share": round(would_be_share, 3),
            "max_allowed": self.max_concentration,
            "risk_score": round(risk_score, 3),
            "veto": veto,
            "veto_reason": VetoReason.CONCENTRATION_RISK if veto else None,
        }


class KRIStatusEvaluator:
    """Evaluates risk based on current KRI status."""

    def __init__(self, kri_engine=None):
        self.kri_engine = kri_engine

    def evaluate(self, candidate: OptimizationCandidate) -> Dict[str, Any]:
        if not self.kri_engine:
            return {"factor": "kri_status", "risk_score": 0.0, "veto": False, "veto_reason": None}

        linked_kris = candidate.metadata.get("linked_kris", [])
        max_risk = 0.0
        red_kris = []

        for kri_id in linked_kris:
            latest = self.kri_engine.latest(kri_id)
            if latest:
                kri_risk = {"green": 0.0, "amber": 0.5, "red": 1.0}[latest.status.value]
                if latest.status.value == "red":
                    red_kris.append(kri_id)
                max_risk = max(max_risk, kri_risk)

        return {
            "factor": "kri_status",
            "linked_kris": linked_kris,
            "red_kris": red_kris,
            "risk_score": max_risk,
            "veto": len(red_kris) > 0,
            "veto_reason": VetoReason.KRI_RED if red_kris else None,
        }


# ── Risk-Adjusted Optimizer ────────────────────────────────────────────────

class RiskAdjustedOptimizer:
    """
    Makes Trainer optimization decisions risk-aware.

    Usage:
        optimizer = RiskAdjustedOptimizer()
        candidates = [
            OptimizationCandidate("claude", "Anthropic Claude", accuracy=0.95, cost=0.7, ...),
            OptimizationCandidate("local", "Ollama Llama", accuracy=0.85, cost=0.1, ...),
        ]
        decision = optimizer.optimize("model_selection", candidates, data_tier="internal")
    """

    def __init__(self, kri_engine=None, audit_callback=None):
        self.provenance_eval = ModelProvenanceEvaluator()
        self.sovereignty_eval = DataSovereigntyEvaluator()
        self.concentration_eval = VendorConcentrationEvaluator()
        self.kri_eval = KRIStatusEvaluator(kri_engine)
        self._audit_callback = audit_callback

    def optimize(self, decision_type: str, candidates: List[OptimizationCandidate],
                 data_tier: str = "public") -> OptimizationDecision:
        """
        Evaluate candidates and select the risk-adjusted optimal choice.

        Returns the selected candidate with full risk assessment.
        """
        weights = DECISION_WEIGHTS.get(decision_type, RiskWeights())
        now = datetime.now(timezone.utc).isoformat()

        # Assess risk for each candidate
        for candidate in candidates:
            assessment = self._assess_risk(candidate, data_tier)
            candidate.risk_assessment = assessment

            if assessment.vetoed:
                candidate.composite_score = -1.0  # Vetoed
            else:
                # Composite: higher accuracy is better, lower cost is better, lower risk is better
                candidate.composite_score = (
                    candidate.accuracy_score * weights.accuracy
                    + (1.0 - candidate.cost_score) * weights.cost
                    + (1.0 - assessment.risk_score) * weights.risk
                )

        # Sort by composite score (highest first), excluding vetoed
        viable = [c for c in candidates if not c.risk_assessment.vetoed]
        viable.sort(key=lambda c: c.composite_score, reverse=True)

        # Check if risk vetoed the accuracy-optimal choice
        accuracy_best = max(candidates, key=lambda c: c.accuracy_score)
        risk_override = (accuracy_best.risk_assessment.vetoed or
                         (viable and viable[0].candidate_id != accuracy_best.candidate_id))

        selected = viable[0] if viable else None
        reason = self._explain_decision(selected, candidates, accuracy_best, risk_override)

        decision = OptimizationDecision(
            decision_type=decision_type,
            selected=selected,
            candidates=candidates,
            decision_reason=reason,
            risk_override=risk_override,
            timestamp=now,
        )

        if selected:
            self.concentration_eval.record_usage(
                selected.metadata.get("provider", "unknown"))

        self._emit_audit(decision)
        return decision

    def _assess_risk(self, candidate: OptimizationCandidate,
                     data_tier: str) -> RiskAssessment:
        """Run all risk evaluators against a candidate."""
        factors = []
        veto_reasons = []
        warnings = []
        risk_scores = []

        # Provenance
        prov = self.provenance_eval.evaluate(candidate)
        factors.append(prov)
        risk_scores.append(prov["risk_score"])
        if prov["veto"]:
            veto_reasons.append(prov["veto_reason"])

        # Sovereignty
        sov = self.sovereignty_eval.evaluate(candidate, data_tier)
        factors.append(sov)
        risk_scores.append(sov["risk_score"])
        if sov["veto"]:
            veto_reasons.append(sov["veto_reason"])

        # Concentration
        conc = self.concentration_eval.evaluate(candidate)
        factors.append(conc)
        risk_scores.append(conc["risk_score"])
        if conc["veto"]:
            veto_reasons.append(conc["veto_reason"])
        elif conc["risk_score"] > 0.7:
            warnings.append(f"Vendor concentration at {conc.get('projected_share', 0):.0%}")

        # KRI
        kri = self.kri_eval.evaluate(candidate)
        factors.append(kri)
        risk_scores.append(kri["risk_score"])
        if kri["veto"]:
            veto_reasons.append(kri["veto_reason"])

        # Aggregate risk score (max of individual factors — conservative)
        aggregate = max(risk_scores) if risk_scores else 0.0

        return RiskAssessment(
            risk_score=round(aggregate, 3),
            factors=factors,
            vetoed=len(veto_reasons) > 0,
            veto_reasons=veto_reasons,
            warnings=warnings,
        )

    def _explain_decision(self, selected, candidates, accuracy_best, risk_override):
        if not selected:
            vetoed_reasons = set()
            for c in candidates:
                for v in (c.risk_assessment.veto_reasons if c.risk_assessment else []):
                    vetoed_reasons.add(v.value)
            return f"All candidates vetoed by risk. Reasons: {', '.join(vetoed_reasons)}"

        if risk_override:
            return (f"Selected {selected.candidate_id} (composite={selected.composite_score:.3f}) "
                    f"over accuracy-optimal {accuracy_best.candidate_id} "
                    f"due to risk factors (risk_score={accuracy_best.risk_assessment.risk_score:.3f})")

        return (f"Selected {selected.candidate_id} "
                f"(composite={selected.composite_score:.3f}, "
                f"accuracy={selected.accuracy_score:.2f}, "
                f"cost={selected.cost_score:.2f}, "
                f"risk={selected.risk_assessment.risk_score:.3f})")

    def _emit_audit(self, decision: OptimizationDecision):
        if self._audit_callback:
            self._audit_callback({
                "timestamp": decision.timestamp,
                "component": "risk.optimizer",
                "event_type": "optimization_decision",
                "details": {
                    "decision_type": decision.decision_type,
                    "selected": decision.selected.candidate_id if decision.selected else None,
                    "risk_override": decision.risk_override,
                    "reason": decision.decision_reason,
                    "candidates_evaluated": len(decision.candidates),
                    "candidates_vetoed": sum(1 for c in decision.candidates if c.risk_assessment and c.risk_assessment.vetoed),
                },
            })


# ── Demo ────────────────────────────────────────────────────────────────────

def demo():
    print("=" * 70)
    print("STC Risk-Adjusted Optimizer — Demo")
    print("=" * 70)

    audit_log = []
    optimizer = RiskAdjustedOptimizer(audit_callback=lambda e: audit_log.append(e))

    # ── Scenario 1: Model Selection (public data) ──
    print("\n▸ Scenario 1: Model selection for PUBLIC data")
    candidates = [
        OptimizationCandidate("claude-sonnet", "Anthropic Claude Sonnet", 0.95, 0.70,
                              {"provenance_trust": "verified", "provider": "anthropic",
                               "provider_type": "external", "allowed_tiers": ["public", "internal"]}),
        OptimizationCandidate("gpt-4o", "OpenAI GPT-4o", 0.93, 0.80,
                              {"provenance_trust": "verified", "provider": "openai",
                               "provider_type": "external", "allowed_tiers": ["public"]}),
        OptimizationCandidate("llama-local", "Ollama Llama 3.1", 0.82, 0.10,
                              {"provenance_trust": "trusted", "provider": "local",
                               "provider_type": "local", "allowed_tiers": ["public", "internal", "restricted"]}),
    ]
    decision = optimizer.optimize("model_selection", candidates, "public")
    print_decision(decision)

    # ── Scenario 2: Model Selection (restricted data) ──
    print("\n▸ Scenario 2: Model selection for RESTRICTED data")
    decision2 = optimizer.optimize("model_selection", [
        OptimizationCandidate("claude-sonnet", "Anthropic Claude", 0.95, 0.70,
                              {"provenance_trust": "verified", "provider": "anthropic",
                               "provider_type": "external", "allowed_tiers": ["public", "internal"]}),
        OptimizationCandidate("llama-local", "Ollama Llama 3.1", 0.82, 0.10,
                              {"provenance_trust": "trusted", "provider": "local",
                               "provider_type": "local", "allowed_tiers": ["public", "internal", "restricted"]}),
    ], "restricted")
    print_decision(decision2)

    # ── Scenario 3: Suspicious model vetoed ──
    print("\n▸ Scenario 3: Suspicious model (higher accuracy) vetoed")
    decision3 = optimizer.optimize("model_selection", [
        OptimizationCandidate("suspicious-model", "Unknown Fine-Tune v2", 0.98, 0.05,
                              {"provenance_trust": "suspicious", "provider": "unknown",
                               "provider_type": "external", "allowed_tiers": ["public"]}),
        OptimizationCandidate("claude-sonnet", "Anthropic Claude", 0.93, 0.70,
                              {"provenance_trust": "verified", "provider": "anthropic",
                               "provider_type": "external", "allowed_tiers": ["public", "internal"]}),
    ], "public")
    print_decision(decision3)

    # ── Scenario 4: Fallback activation (high risk weight) ──
    print("\n▸ Scenario 4: Fallback activation (70% risk weight)")
    decision4 = optimizer.optimize("fallback_activation", [
        OptimizationCandidate("bedrock", "AWS Bedrock Claude", 0.93, 0.60,
                              {"provenance_trust": "verified", "provider": "bedrock",
                               "provider_type": "vpc", "allowed_tiers": ["public", "internal", "restricted"]}),
        OptimizationCandidate("openai", "OpenAI GPT-4", 0.95, 0.80,
                              {"provenance_trust": "verified", "provider": "openai",
                               "provider_type": "external", "allowed_tiers": ["public"]}),
    ], "internal")
    print_decision(decision4)

    # ── Decision Weights ──
    print("\n▸ Decision risk weights:")
    for dt, w in DECISION_WEIGHTS.items():
        print(f"  {dt}: accuracy={w.accuracy:.0%} cost={w.cost:.0%} risk={w.risk:.0%}")

    print(f"\n▸ Audit events: {len(audit_log)}")
    for e in audit_log:
        d = e["details"]
        print(f"  [{d['decision_type']}] selected={d['selected']}, "
              f"override={d['risk_override']}, vetoed={d['candidates_vetoed']}")

    print("\n" + "=" * 70)
    print("✓ Risk-adjusted optimizer demo complete")
    print("=" * 70)


def print_decision(decision: OptimizationDecision):
    sel = decision.selected
    print(f"  Decision: {decision.decision_type}")
    if sel:
        print(f"  Selected: {sel.candidate_id} (composite={sel.composite_score:.3f})")
        print(f"    Accuracy={sel.accuracy_score:.2f}, Cost={sel.cost_score:.2f}, "
              f"Risk={sel.risk_assessment.risk_score:.3f}")
    else:
        print(f"  Selected: NONE (all vetoed)")
    print(f"  Risk override: {decision.risk_override}")
    print(f"  Reason: {decision.decision_reason}")

    for c in decision.candidates:
        ra = c.risk_assessment
        v = " [VETOED]" if ra and ra.vetoed else ""
        w = f" ⚠ {ra.warnings}" if ra and ra.warnings else ""
        print(f"    {c.candidate_id}: composite={c.composite_score:.3f}, "
              f"risk={ra.risk_score:.3f}{v}{w}")
        if ra and ra.vetoed:
            for vr in ra.veto_reasons:
                print(f"      └─ Veto: {vr.value}")


if __name__ == "__main__":
    demo()
