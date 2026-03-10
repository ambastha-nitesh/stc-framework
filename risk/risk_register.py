"""
STC Framework — Risk Register & KRI Engine
risk/risk_register.py

Enterprise risk management implementation:
  - Risk Register: lifecycle management (identify, assess, treat, accept, monitor, close)
  - KRI Engine: automated Key Risk Indicator monitoring with thresholds
  - Risk Scoring: 5x5 semi-quantitative matrix (ISO 31000 aligned)
  - Risk Appetite Monitoring: automated breach detection
  - Risk Reporting: dashboard-ready outputs for committee and board

Aligned with COSO ERM 2017, ISO 31000:2018, NIST AI RMF.
"""

import json
import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stc.risk.register")


# ── Enums ───────────────────────────────────────────────────────────────────

class RiskCategory(Enum):
    TECHNOLOGY = "technology"
    STRATEGIC = "strategic"
    REGULATORY = "regulatory"
    OPERATIONAL = "operational"
    REPUTATIONAL = "reputational"


class Likelihood(Enum):
    RARE = 1
    UNLIKELY = 2
    POSSIBLE = 3
    LIKELY = 4
    ALMOST_CERTAIN = 5


class Impact(Enum):
    INSIGNIFICANT = 1
    MINOR = 2
    MODERATE = 3
    MAJOR = 4
    CATASTROPHIC = 5


class RiskRating(Enum):
    LOW = "low"             # 1-4
    MEDIUM = "medium"       # 5-9
    HIGH = "high"           # 10-15
    CRITICAL = "critical"   # 16-25


class TreatmentType(Enum):
    ACCEPT = "accept"
    MITIGATE = "mitigate"
    TRANSFER = "transfer"
    AVOID = "avoid"


class RiskState(Enum):
    IDENTIFIED = "identified"
    ASSESSED = "assessed"
    TREATMENT_PLANNED = "treatment_planned"
    ACCEPTED = "accepted"
    MONITORING = "monitoring"
    CLOSED = "closed"
    ESCALATED = "escalated"


class KRIStatus(Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class KRIType(Enum):
    LEADING = "leading"
    LAGGING = "lagging"


# ── Risk Scoring ────────────────────────────────────────────────────────────

def compute_risk_score(likelihood: int, impact: int) -> int:
    return likelihood * impact


def classify_risk(score: int) -> RiskRating:
    if score >= 16:
        return RiskRating.CRITICAL
    elif score >= 10:
        return RiskRating.HIGH
    elif score >= 5:
        return RiskRating.MEDIUM
    return RiskRating.LOW


def mitigation_sla_days(rating: RiskRating) -> int:
    return {RiskRating.CRITICAL: 0, RiskRating.HIGH: 30,
            RiskRating.MEDIUM: 90, RiskRating.LOW: 180}[rating]


# ── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class RiskTreatment:
    treatment_type: TreatmentType
    description: str
    controls: List[str]           # Control IDs from control inventory
    owner: str
    target_date: str
    status: str = "planned"       # planned | in_progress | completed

@dataclass
class RiskAcceptance:
    accepted_by: str
    accepted_date: str
    conditions: str
    review_date: str
    committee_decision_ref: str = ""

@dataclass
class Risk:
    risk_id: str
    title: str
    description: str
    category: RiskCategory
    state: RiskState
    # Inherent risk (before controls)
    inherent_likelihood: Likelihood
    inherent_impact: Impact
    # Residual risk (after controls)
    residual_likelihood: Optional[Likelihood] = None
    residual_impact: Optional[Impact] = None
    # Treatment
    treatment: Optional[RiskTreatment] = None
    acceptance: Optional[RiskAcceptance] = None
    # Metadata
    owner: str = ""
    identified_by: str = ""
    identified_date: str = ""
    last_assessed: str = ""
    kri_ids: List[str] = field(default_factory=list)
    linked_scenario_ids: List[str] = field(default_factory=list)
    nist_ai_rmf_ref: str = ""
    notes: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def inherent_score(self) -> int:
        return compute_risk_score(self.inherent_likelihood.value, self.inherent_impact.value)

    @property
    def inherent_rating(self) -> RiskRating:
        return classify_risk(self.inherent_score)

    @property
    def residual_score(self) -> Optional[int]:
        if self.residual_likelihood and self.residual_impact:
            return compute_risk_score(self.residual_likelihood.value, self.residual_impact.value)
        return None

    @property
    def residual_rating(self) -> Optional[RiskRating]:
        s = self.residual_score
        return classify_risk(s) if s else None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_id": self.risk_id, "title": self.title, "description": self.description,
            "category": self.category.value, "state": self.state.value, "owner": self.owner,
            "inherent": {"likelihood": self.inherent_likelihood.name, "impact": self.inherent_impact.name,
                         "score": self.inherent_score, "rating": self.inherent_rating.value},
            "residual": {"likelihood": self.residual_likelihood.name if self.residual_likelihood else None,
                         "impact": self.residual_impact.name if self.residual_impact else None,
                         "score": self.residual_score,
                         "rating": self.residual_rating.value if self.residual_rating else None},
            "treatment": {"type": self.treatment.treatment_type.value, "description": self.treatment.description,
                          "controls": self.treatment.controls, "status": self.treatment.status}
                         if self.treatment else None,
            "acceptance": {"accepted_by": self.acceptance.accepted_by, "date": self.acceptance.accepted_date,
                           "conditions": self.acceptance.conditions} if self.acceptance else None,
            "kri_ids": self.kri_ids, "linked_scenarios": self.linked_scenario_ids,
        }


# ── KRI Definition ──────────────────────────────────────────────────────────

@dataclass
class KRIDefinition:
    kri_id: str
    name: str
    description: str
    kri_type: KRIType
    unit: str
    green_threshold: float        # Below this = green
    amber_threshold: float        # Below this = amber, above green = amber
    red_threshold: float          # Above this = red
    measurement_frequency: str    # daily, weekly, monthly
    linked_risk_ids: List[str] = field(default_factory=list)
    escalation_trigger: str = ""
    higher_is_worse: bool = True  # True = higher value = more risk

    def evaluate(self, value: float) -> KRIStatus:
        if self.higher_is_worse:
            if value <= self.green_threshold:
                return KRIStatus.GREEN
            elif value <= self.amber_threshold:
                return KRIStatus.AMBER
            return KRIStatus.RED
        else:
            # Lower is worse (e.g., availability)
            if value >= self.green_threshold:
                return KRIStatus.GREEN
            elif value >= self.amber_threshold:
                return KRIStatus.AMBER
            return KRIStatus.RED


@dataclass
class KRIMeasurement:
    kri_id: str
    value: float
    status: KRIStatus
    timestamp: str
    notes: str = ""


# ── Default KRI Library ─────────────────────────────────────────────────────

DEFAULT_KRIS = [
    # Leading indicators
    KRIDefinition("KRI-L01", "Prompt injection attempt rate", "Firewall-blocked attacks per 1K requests",
                  KRIType.LEADING, "per 1K", 5, 20, 20, "daily", ["T-002"], "Security review at amber"),
    KRIDefinition("KRI-L02", "Model provenance alerts", "Integrity check warnings (7-day window)",
                  KRIType.LEADING, "count", 0, 2, 2, "weekly", ["T-004"], "Quarantine at red"),
    KRIDefinition("KRI-L04", "Error budget burn rate", "% of 30-day error budget consumed",
                  KRIType.LEADING, "%", 50, 80, 80, "daily", ["T-009"], "Change freeze at red"),
    KRIDefinition("KRI-L06", "Cost trajectory", "Projected monthly cost vs budget %",
                  KRIType.LEADING, "%", 100, 120, 120, "weekly", ["S-004"], "Committee review at red"),
    KRIDefinition("KRI-L07", "Open exception aging", "% of exceptions past SLA",
                  KRIType.LEADING, "%", 0, 10, 10, "weekly", [], "Escalation at red"),
    # Lagging indicators
    KRIDefinition("KRI-G01", "Hallucination rate", "% of responses flagged by Critic",
                  KRIType.LAGGING, "%", 1, 2, 2, "daily", ["T-001"], "Trainer review at amber"),
    KRIDefinition("KRI-G02", "Data sovereignty incidents", "Restricted data boundary crossings",
                  KRIType.LAGGING, "count", 0, 0, 0, "real-time", ["T-003"], "Immediate halt at any"),
    KRIDefinition("KRI-G04", "Scope violations", "AI investment advice instances",
                  KRIType.LAGGING, "count", 0, 0, 0, "real-time", ["T-006"], "Immediate halt at any"),
    KRIDefinition("KRI-G05", "System availability", "Monthly uptime %",
                  KRIType.LAGGING, "%", 99.95, 99.9, 99.9, "monthly", ["T-009"],
                  "Post-incident review at amber", False),
    KRIDefinition("KRI-G06", "Control test pass rate", "% of tests passing",
                  KRIType.LAGGING, "%", 95, 85, 85, "weekly", [],
                  "Committee notification at red", False),
]


# ── Risk Register ───────────────────────────────────────────────────────────

class RiskRegister:
    """
    Enterprise risk register for the STC Framework.

    Usage:
        reg = RiskRegister()
        risk_id = reg.identify("Hallucination", ..., Likelihood.POSSIBLE, Impact.MAJOR)
        reg.assess(risk_id, residual_likelihood=..., residual_impact=...)
        reg.treat(risk_id, RiskTreatment(...))
        reg.accept(risk_id, RiskAcceptance(...))
        dashboard = reg.risk_dashboard()
    """

    def __init__(self, audit_callback=None):
        self._risks: Dict[str, Risk] = {}
        self._counter = 0
        self._audit_callback = audit_callback

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _gen_id(self, category: RiskCategory) -> str:
        self._counter += 1
        prefix = {"technology": "T", "strategic": "S", "regulatory": "R",
                   "operational": "O", "reputational": "REP"}[category.value]
        return f"{prefix}-{self._counter:03d}"

    def identify(self, title: str, description: str, category: RiskCategory,
                 likelihood: Likelihood, impact: Impact, owner: str = "",
                 identified_by: str = "system", nist_ref: str = "",
                 kri_ids: List[str] = None, scenario_ids: List[str] = None) -> str:
        """Identify and register a new risk."""
        risk_id = self._gen_id(category)
        now = self._now()

        risk = Risk(
            risk_id=risk_id, title=title, description=description,
            category=category, state=RiskState.IDENTIFIED,
            inherent_likelihood=likelihood, inherent_impact=impact,
            owner=owner, identified_by=identified_by, identified_date=now,
            nist_ai_rmf_ref=nist_ref, kri_ids=kri_ids or [], linked_scenario_ids=scenario_ids or [],
        )
        risk.history.append({"action": "identified", "timestamp": now, "actor": identified_by})

        self._risks[risk_id] = risk
        self._emit("risk_identified", risk_id, {
            "title": title, "inherent_score": risk.inherent_score,
            "rating": risk.inherent_rating.value,
        })
        return risk_id

    def assess(self, risk_id: str, residual_likelihood: Likelihood,
               residual_impact: Impact, actor: str = "risk-team"):
        """Assess residual risk after controls."""
        risk = self._get(risk_id)
        risk.residual_likelihood = residual_likelihood
        risk.residual_impact = residual_impact
        risk.state = RiskState.ASSESSED
        risk.last_assessed = self._now()
        risk.history.append({"action": "assessed", "timestamp": self._now(), "actor": actor,
                             "residual_score": risk.residual_score})
        self._emit("risk_assessed", risk_id, {
            "residual_score": risk.residual_score, "residual_rating": risk.residual_rating.value,
        })

    def treat(self, risk_id: str, treatment: RiskTreatment, actor: str = "engineering"):
        """Attach a risk treatment plan."""
        risk = self._get(risk_id)
        risk.treatment = treatment
        risk.state = RiskState.TREATMENT_PLANNED
        risk.history.append({"action": "treatment_planned", "timestamp": self._now(),
                             "actor": actor, "type": treatment.treatment_type.value})

    def accept(self, risk_id: str, acceptance: RiskAcceptance, actor: str = "committee"):
        """Formally accept the residual risk."""
        risk = self._get(risk_id)
        risk.acceptance = acceptance
        risk.state = RiskState.ACCEPTED
        risk.history.append({"action": "accepted", "timestamp": self._now(),
                             "actor": actor, "accepted_by": acceptance.accepted_by})
        self._emit("risk_accepted", risk_id, {
            "accepted_by": acceptance.accepted_by, "conditions": acceptance.conditions,
        })

    def start_monitoring(self, risk_id: str):
        """Move risk to active monitoring."""
        risk = self._get(risk_id)
        risk.state = RiskState.MONITORING
        risk.history.append({"action": "monitoring_started", "timestamp": self._now()})

    def escalate(self, risk_id: str, reason: str, actor: str = "kri_engine"):
        """Escalate a risk due to KRI breach or material change."""
        risk = self._get(risk_id)
        risk.state = RiskState.ESCALATED
        risk.history.append({"action": "escalated", "timestamp": self._now(),
                             "actor": actor, "reason": reason})
        self._emit("risk_escalated", risk_id, {"reason": reason})

    def close(self, risk_id: str, reason: str, actor: str = "committee"):
        """Close a risk (mitigated, transferred, or no longer applicable)."""
        risk = self._get(risk_id)
        risk.state = RiskState.CLOSED
        risk.history.append({"action": "closed", "timestamp": self._now(),
                             "actor": actor, "reason": reason})

    # ── Reporting ───────────────────────────────────────────────────────

    def risk_dashboard(self) -> Dict[str, Any]:
        """Generate risk dashboard data for committee reporting."""
        by_rating = defaultdict(int)
        by_category = defaultdict(int)
        by_state = defaultdict(int)
        escalated = []
        critical = []

        for risk in self._risks.values():
            rating = risk.residual_rating or risk.inherent_rating
            by_rating[rating.value] += 1
            by_category[risk.category.value] += 1
            by_state[risk.state.value] += 1
            if risk.state == RiskState.ESCALATED:
                escalated.append(risk.risk_id)
            if rating == RiskRating.CRITICAL:
                critical.append(risk.risk_id)

        return {
            "generated": self._now(),
            "total_risks": len(self._risks),
            "by_rating": dict(by_rating),
            "by_category": dict(by_category),
            "by_state": dict(by_state),
            "escalated_risks": escalated,
            "critical_risks": critical,
            "appetite_breaches": [],  # Populated by KRI engine
        }

    def heat_map(self) -> List[Dict[str, Any]]:
        """Generate data for a risk heat map visualization."""
        return [
            {
                "risk_id": r.risk_id, "title": r.title,
                "likelihood": (r.residual_likelihood or r.inherent_likelihood).value,
                "impact": (r.residual_impact or r.inherent_impact).value,
                "score": r.residual_score or r.inherent_score,
                "rating": (r.residual_rating or r.inherent_rating).value,
                "category": r.category.value,
            }
            for r in self._risks.values() if r.state != RiskState.CLOSED
        ]

    def export(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._risks.values()]

    def _get(self, risk_id: str) -> Risk:
        if risk_id not in self._risks:
            raise KeyError(f"Risk not found: {risk_id}")
        return self._risks[risk_id]

    def _emit(self, event_type, risk_id, details):
        if self._audit_callback:
            self._audit_callback({
                "timestamp": self._now(), "component": "risk.register",
                "event_type": event_type, "risk_id": risk_id, "details": details,
            })


# ── KRI Engine ──────────────────────────────────────────────────────────────

class KRIEngine:
    """
    Monitors Key Risk Indicators and triggers risk escalations.

    Usage:
        engine = KRIEngine(risk_register=register)
        engine.record("KRI-G01", 1.5)  # Hallucination rate = 1.5%
        dashboard = engine.dashboard()
        breaches = engine.check_appetite()
    """

    def __init__(self, kri_definitions: Optional[List[KRIDefinition]] = None,
                 risk_register: Optional[RiskRegister] = None,
                 audit_callback=None):
        self.kris = {k.kri_id: k for k in (kri_definitions or DEFAULT_KRIS)}
        self.register = risk_register
        self._measurements: Dict[str, List[KRIMeasurement]] = defaultdict(list)
        self._audit_callback = audit_callback

    def record(self, kri_id: str, value: float, notes: str = "") -> KRIMeasurement:
        """Record a KRI measurement and evaluate against thresholds."""
        kri = self.kris.get(kri_id)
        if not kri:
            raise KeyError(f"KRI not found: {kri_id}")

        status = kri.evaluate(value)
        now = datetime.now(timezone.utc).isoformat()

        measurement = KRIMeasurement(
            kri_id=kri_id, value=value, status=status, timestamp=now, notes=notes)
        self._measurements[kri_id].append(measurement)

        # Check for status change
        prev = self._measurements[kri_id][-2] if len(self._measurements[kri_id]) > 1 else None
        if prev and prev.status != status:
            self._on_status_change(kri, prev.status, status, value)

        # Auto-escalate linked risks on RED
        if status == KRIStatus.RED and self.register:
            for risk_id in kri.linked_risk_ids:
                try:
                    risk = self.register._get(risk_id)
                    if risk.state in (RiskState.MONITORING, RiskState.ACCEPTED):
                        self.register.escalate(risk_id,
                                               f"KRI {kri_id} ({kri.name}) breached RED threshold: {value}{kri.unit}")
                except KeyError:
                    pass

        if self._audit_callback:
            self._audit_callback({
                "timestamp": now, "component": "risk.kri_engine",
                "event_type": "kri_measurement",
                "details": {"kri_id": kri_id, "value": value, "status": status.value},
            })

        return measurement

    def _on_status_change(self, kri: KRIDefinition, old: KRIStatus, new: KRIStatus, value: float):
        direction = "deteriorated" if new.value > old.value else "improved"
        logger.info(f"KRI [{kri.kri_id}] {kri.name}: {old.value} → {new.value} ({direction})")
        if new == KRIStatus.RED:
            logger.warning(f"KRI [{kri.kri_id}] RED: {kri.escalation_trigger}")

    def latest(self, kri_id: str) -> Optional[KRIMeasurement]:
        """Get the most recent measurement for a KRI."""
        measurements = self._measurements.get(kri_id)
        return measurements[-1] if measurements else None

    def trend(self, kri_id: str, periods: int = 10) -> List[Dict[str, Any]]:
        """Get recent trend data for a KRI."""
        measurements = self._measurements.get(kri_id, [])
        return [
            {"value": m.value, "status": m.status.value, "timestamp": m.timestamp}
            for m in measurements[-periods:]
        ]

    def dashboard(self) -> Dict[str, Any]:
        """Generate KRI dashboard for risk reporting."""
        indicators = []
        reds = []
        ambers = []

        for kri_id, kri in self.kris.items():
            latest = self.latest(kri_id)
            entry = {
                "kri_id": kri_id, "name": kri.name, "type": kri.kri_type.value,
                "status": latest.status.value if latest else "unmeasured",
                "value": latest.value if latest else None,
                "unit": kri.unit,
                "thresholds": {"green": kri.green_threshold, "amber": kri.amber_threshold,
                               "red": kri.red_threshold},
                "measurement_count": len(self._measurements.get(kri_id, [])),
            }
            indicators.append(entry)
            if latest:
                if latest.status == KRIStatus.RED:
                    reds.append(kri_id)
                elif latest.status == KRIStatus.AMBER:
                    ambers.append(kri_id)

        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "total_kris": len(self.kris),
            "green": len(indicators) - len(reds) - len(ambers),
            "amber": len(ambers),
            "red": len(reds),
            "red_kris": reds,
            "amber_kris": ambers,
            "indicators": indicators,
        }

    def check_appetite(self) -> List[Dict[str, Any]]:
        """Check all KRIs against risk appetite thresholds. Returns breaches."""
        breaches = []
        for kri_id, kri in self.kris.items():
            latest = self.latest(kri_id)
            if latest and latest.status == KRIStatus.RED:
                breaches.append({
                    "kri_id": kri_id, "name": kri.name, "value": latest.value,
                    "threshold": kri.red_threshold, "escalation": kri.escalation_trigger,
                    "linked_risks": kri.linked_risk_ids,
                })
        return breaches


# ── Demo ────────────────────────────────────────────────────────────────────

def demo():
    print("=" * 70)
    print("STC Risk Register & KRI Engine — Demo")
    print("=" * 70)

    audit_log = []
    cb = lambda e: audit_log.append(e)

    register = RiskRegister(audit_callback=cb)
    engine = KRIEngine(risk_register=register, audit_callback=cb)

    # ── Populate Risk Register ──
    print("\n▸ Identifying risks...")

    r1 = register.identify(
        "Hallucination in financial responses", "AI generates incorrect financial data presented as fact",
        RiskCategory.TECHNOLOGY, Likelihood.POSSIBLE, Impact.MAJOR,
        owner="AI Engineering", nist_ref="MANAGE 2.2", kri_ids=["KRI-G01"], scenario_ids=["SCN-003"])

    r2 = register.identify(
        "Data sovereignty breach", "Restricted data sent to external LLM provider",
        RiskCategory.TECHNOLOGY, Likelihood.UNLIKELY, Impact.CATASTROPHIC,
        owner="CISO", nist_ref="GOVERN 1.6", kri_ids=["KRI-G02"], scenario_ids=["SCN-002"])

    r3 = register.identify(
        "Prompt injection attack", "Adversary manipulates AI behavior through crafted inputs",
        RiskCategory.TECHNOLOGY, Likelihood.POSSIBLE, Impact.MAJOR,
        owner="Security Team", nist_ref="MANAGE 2.3", kri_ids=["KRI-L01"], scenario_ids=["SCN-004"])

    r4 = register.identify(
        "AI commoditization of platform value", "GenAI erodes differentiation of platform offering",
        RiskCategory.STRATEGIC, Likelihood.LIKELY, Impact.MAJOR,
        owner="Global CIO", kri_ids=[], scenario_ids=[])

    for rid in [r1, r2, r3, r4]:
        risk = register._get(rid)
        print(f"  [{rid}] {risk.title}: inherent={risk.inherent_rating.value} ({risk.inherent_score})")

    # ── Assess Residual Risk ──
    print("\n▸ Assessing residual risks...")
    register.assess(r1, Likelihood.UNLIKELY, Impact.MODERATE)
    register.assess(r2, Likelihood.RARE, Impact.MAJOR)
    register.assess(r3, Likelihood.UNLIKELY, Impact.MODERATE)

    for rid in [r1, r2, r3]:
        risk = register._get(rid)
        print(f"  [{rid}] residual={risk.residual_rating.value} ({risk.residual_score}) "
              f"(from inherent={risk.inherent_rating.value})")

    # ── Treat & Accept ──
    print("\n▸ Treating and accepting risks...")
    register.treat(r1, RiskTreatment(
        TreatmentType.MITIGATE, "Critic validators + numerical accuracy checks",
        ["GOV-001", "GOV-002"], "AI Engineering", "2026-04-01", "completed"))
    register.accept(r1, RiskAcceptance(
        "AI Governance Committee", "2026-03-09", "Hallucination rate must remain < 2%",
        "2026-06-09", "AIGC-2026-003"))
    register.start_monitoring(r1)
    print(f"  [{r1}] treated, accepted, monitoring")

    register.treat(r2, RiskTreatment(
        TreatmentType.MITIGATE, "Gateway data tier enforcement + PII masking",
        ["SEC-002", "SEC-003"], "CISO", "2026-03-15", "completed"))
    register.accept(r2, RiskAcceptance(
        "CISO + DPO", "2026-03-09", "Zero tolerance — any breach triggers immediate halt",
        "2026-06-09", "AIGC-2026-004"))
    register.start_monitoring(r2)
    print(f"  [{r2}] treated, accepted, monitoring")

    # ── KRI Measurements ──
    print("\n▸ Recording KRI measurements...")

    # Normal readings
    engine.record("KRI-G01", 0.8, "Daily hallucination rate")
    engine.record("KRI-G02", 0, "No sovereignty incidents")
    engine.record("KRI-L01", 3, "Normal injection attempt rate")
    engine.record("KRI-G05", 99.97, "Monthly availability")
    engine.record("KRI-G06", 96, "Control test pass rate")
    engine.record("KRI-L04", 35, "Error budget burn rate")
    engine.record("KRI-L06", 95, "Cost vs budget")
    print("  Normal readings recorded")

    # Deteriorating hallucination rate
    print("\n▸ Simulating deteriorating hallucination rate...")
    engine.record("KRI-G01", 1.2, "Slight increase noted")
    engine.record("KRI-G01", 1.8, "Approaching amber threshold")
    engine.record("KRI-G01", 2.5, "BREACH — above 2% tolerance")

    # ── KRI Dashboard ──
    print("\n▸ KRI Dashboard:")
    dashboard = engine.dashboard()
    print(f"  Total KRIs: {dashboard['total_kris']}")
    print(f"  Green: {dashboard['green']} | Amber: {dashboard['amber']} | Red: {dashboard['red']}")
    if dashboard['red_kris']:
        print(f"  RED KRIs: {dashboard['red_kris']}")
    if dashboard['amber_kris']:
        print(f"  AMBER KRIs: {dashboard['amber_kris']}")

    for ind in dashboard["indicators"]:
        if ind["value"] is not None:
            icon = {"green": "●", "amber": "◉", "red": "◉", "unmeasured": "○"}
            color = {"green": "", "amber": " ⚠", "red": " 🔴", "unmeasured": ""}
            print(f"    {icon[ind['status']]} [{ind['kri_id']}] {ind['name']}: "
                  f"{ind['value']}{ind['unit']} ({ind['status']}{color[ind['status']]})")

    # ── Appetite Check ──
    print("\n▸ Risk appetite breach check:")
    breaches = engine.check_appetite()
    for b in breaches:
        print(f"  🔴 {b['kri_id']} ({b['name']}): {b['value']} > {b['threshold']} — {b['escalation']}")
    if not breaches:
        print("  No appetite breaches")

    # ── Risk Dashboard ──
    print("\n▸ Risk Dashboard:")
    rd = register.risk_dashboard()
    print(f"  Total risks: {rd['total_risks']}")
    print(f"  By rating: {rd['by_rating']}")
    print(f"  By state: {rd['by_state']}")
    if rd['escalated_risks']:
        print(f"  Escalated: {rd['escalated_risks']}")

    # ── Heat Map ──
    print("\n▸ Risk Heat Map:")
    for r in register.heat_map():
        print(f"  [{r['risk_id']}] {r['title'][:40]}... "
              f"L={r['likelihood']} × I={r['impact']} = {r['score']} ({r['rating']})")

    # ── Trend ──
    print("\n▸ KRI-G01 Trend:")
    for t in engine.trend("KRI-G01"):
        print(f"  {t['value']}% ({t['status']})")

    print(f"\n▸ Audit events: {len(audit_log)}")

    print("\n" + "=" * 70)
    print("✓ Risk register & KRI engine demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
