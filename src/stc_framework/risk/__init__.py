"""Enterprise risk management (ISO 31000 + NIST AI RMF aligned).

Three layers, each usable independently:

* :class:`~stc_framework.risk.register.RiskRegister` — catalogs identified
  risks through their lifecycle (identified → assessed → treated →
  monitored → closed/escalated) with a 5x5 likelihood-by-impact matrix.
* :class:`~stc_framework.risk.kri.KRIEngine` — ingests Key Risk Indicator
  measurements, classifies them GREEN/AMBER/RED, auto-escalates linked
  risks when a KRI flips to RED.
* :class:`~stc_framework.risk.optimizer.RiskAdjustedOptimizer` — filters
  Trainer optimization candidates through four risk evaluators
  (provenance, sovereignty, vendor concentration, KRI) and picks the
  composite-optimal non-vetoed candidate.

All three persist via :class:`~stc_framework.infrastructure.store.KeyValueStore`
so multi-process deployments share a single register and KRI window.
"""

from stc_framework.risk.kri import KRIEngine, KRIMeasurement, KRIStatus
from stc_framework.risk.optimizer import (
    OptimizationCandidate,
    OptimizationDecision,
    RiskAdjustedOptimizer,
    RiskAssessment,
    VetoReason,
)
from stc_framework.risk.register import (
    Impact,
    Likelihood,
    Risk,
    RiskCategory,
    RiskRating,
    RiskRegister,
    RiskState,
)

__all__ = [
    "Impact",
    "KRIEngine",
    "KRIMeasurement",
    "KRIStatus",
    "Likelihood",
    "OptimizationCandidate",
    "OptimizationDecision",
    "Risk",
    "RiskAdjustedOptimizer",
    "RiskAssessment",
    "RiskCategory",
    "RiskRating",
    "RiskRegister",
    "RiskState",
    "VetoReason",
]
