"""Enterprise risk register.

Implements the ISO 31000 lifecycle:

    identified → assessed → treatment_planned → accepted → monitoring
                                                         ↳ closed
                                                         ↳ escalated

Each risk carries a 5x5 likelihood-by-impact rating, an inherent rating
(before controls) and a residual rating (after controls), a treatment
plan, and a full transition history via
:class:`stc_framework._internal.state_machine.StatefulRecord`.

Persistence is pluggable (``KeyValueStore``); audit hooks emit
RISK_* events for every lifecycle transition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stc_framework._internal.state_machine import StatefulRecord
from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.metrics import get_metrics, tenant_label


class RiskCategory(str, Enum):
    TECHNOLOGY = "technology"
    STRATEGIC = "strategic"
    REGULATORY = "regulatory"
    OPERATIONAL = "operational"
    REPUTATIONAL = "reputational"


class Likelihood(int, Enum):
    RARE = 1
    UNLIKELY = 2
    POSSIBLE = 3
    LIKELY = 4
    ALMOST_CERTAIN = 5


class Impact(int, Enum):
    INSIGNIFICANT = 1
    MINOR = 2
    MODERATE = 3
    MAJOR = 4
    CATASTROPHIC = 5


class RiskRating(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, likelihood: Likelihood, impact: Impact) -> RiskRating:
        """Standard 5x5 matrix bucketing."""
        score = int(likelihood) * int(impact)
        if score >= 16:
            return cls.CRITICAL
        if score >= 10:
            return cls.HIGH
        if score >= 5:
            return cls.MEDIUM
        return cls.LOW


class RiskState(str, Enum):
    IDENTIFIED = "identified"
    ASSESSED = "assessed"
    TREATMENT_PLANNED = "treatment_planned"
    ACCEPTED = "accepted"
    MONITORING = "monitoring"
    CLOSED = "closed"
    ESCALATED = "escalated"


# Permitted state transitions. Keep this table declarative so auditors
# can verify the lifecycle by reading the source.
RISK_TRANSITIONS: dict[RiskState, set[RiskState]] = {
    RiskState.IDENTIFIED: {RiskState.ASSESSED, RiskState.CLOSED},
    RiskState.ASSESSED: {RiskState.TREATMENT_PLANNED, RiskState.ACCEPTED, RiskState.CLOSED},
    RiskState.TREATMENT_PLANNED: {RiskState.ACCEPTED, RiskState.MONITORING, RiskState.CLOSED},
    RiskState.ACCEPTED: {RiskState.MONITORING, RiskState.CLOSED, RiskState.ESCALATED},
    RiskState.MONITORING: {RiskState.CLOSED, RiskState.ESCALATED, RiskState.ASSESSED},
    RiskState.ESCALATED: {RiskState.TREATMENT_PLANNED, RiskState.MONITORING, RiskState.CLOSED},
    RiskState.CLOSED: set(),
}


@dataclass
class RiskTreatment:
    type: str = "mitigate"  # accept | mitigate | transfer | avoid
    description: str = ""
    owner: str = ""
    due_date: str | None = None
    controls: list[str] = field(default_factory=list)


@dataclass
class Risk:
    """A single identified risk."""

    risk_id: str
    title: str
    description: str = ""
    category: RiskCategory = RiskCategory.OPERATIONAL
    tenant_id: str | None = None
    inherent_likelihood: Likelihood = Likelihood.POSSIBLE
    inherent_impact: Impact = Impact.MODERATE
    residual_likelihood: Likelihood | None = None
    residual_impact: Impact | None = None
    treatment: RiskTreatment | None = None
    linked_kris: list[str] = field(default_factory=list)
    owner: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def inherent_rating(self) -> RiskRating:
        return RiskRating.from_score(self.inherent_likelihood, self.inherent_impact)

    @property
    def residual_rating(self) -> RiskRating | None:
        if self.residual_likelihood is None or self.residual_impact is None:
            return None
        return RiskRating.from_score(self.residual_likelihood, self.residual_impact)


@dataclass
class RiskRecord:
    """What we persist — a :class:`Risk` plus lifecycle state."""

    risk: Risk
    state: StatefulRecord[RiskState]


_KEY_RISK = "risk:register:{risk_id}"


class RiskRegister:
    """CRUD + lifecycle operations for :class:`Risk` records."""

    def __init__(self, store: KeyValueStore, *, audit: AuditLogger | None = None) -> None:
        self._store = store
        self._audit = audit

    async def identify(self, risk: Risk) -> RiskRecord:
        record = RiskRecord(risk=risk, state=StatefulRecord(state=RiskState.IDENTIFIED))
        await self._store.set(_KEY_RISK.format(risk_id=risk.risk_id), _record_to_dict(record))
        await self._emit(AuditEvent.RISK_IDENTIFIED, record, reason="initial identification")
        self._publish_score(record)
        return record

    async def get(self, risk_id: str) -> RiskRecord | None:
        raw = await self._store.get(_KEY_RISK.format(risk_id=risk_id))
        return _record_from_dict(raw) if raw else None

    async def transition(
        self,
        risk_id: str,
        new_state: RiskState,
        *,
        actor: str,
        reason: str,
    ) -> RiskRecord:
        record = await self.get(risk_id)
        if record is None:
            raise KeyError(f"risk not found: {risk_id!r}")
        record.state.transition(new_state, RISK_TRANSITIONS, actor=actor, reason=reason)
        await self._store.set(_KEY_RISK.format(risk_id=risk_id), _record_to_dict(record))
        event_map = {
            RiskState.ASSESSED: AuditEvent.RISK_ASSESSED,
            RiskState.TREATMENT_PLANNED: AuditEvent.RISK_TREATED,
            RiskState.ESCALATED: AuditEvent.RISK_ESCALATED,
        }
        if new_state in event_map:
            await self._emit(event_map[new_state], record, reason=reason)
        return record

    async def assess(
        self,
        risk_id: str,
        *,
        residual_likelihood: Likelihood,
        residual_impact: Impact,
        actor: str,
        reason: str = "assessment",
    ) -> RiskRecord:
        record = await self.get(risk_id)
        if record is None:
            raise KeyError(f"risk not found: {risk_id!r}")
        record.risk.residual_likelihood = residual_likelihood
        record.risk.residual_impact = residual_impact
        await self._store.set(_KEY_RISK.format(risk_id=risk_id), _record_to_dict(record))
        return await self.transition(risk_id, RiskState.ASSESSED, actor=actor, reason=reason)

    async def treat(self, risk_id: str, treatment: RiskTreatment, *, actor: str) -> RiskRecord:
        record = await self.get(risk_id)
        if record is None:
            raise KeyError(f"risk not found: {risk_id!r}")
        record.risk.treatment = treatment
        await self._store.set(_KEY_RISK.format(risk_id=risk_id), _record_to_dict(record))
        return await self.transition(
            risk_id, RiskState.TREATMENT_PLANNED, actor=actor, reason=treatment.description or "treatment planned"
        )

    async def escalate(self, risk_id: str, *, actor: str = "kri_engine", reason: str = "KRI breach") -> RiskRecord:
        return await self.transition(risk_id, RiskState.ESCALATED, actor=actor, reason=reason)

    async def heat_map(self) -> dict[str, int]:
        """Count risks per rating band — for dashboards."""
        buckets: dict[str, int] = {r.value: 0 for r in RiskRating}
        for key in await self._store.keys("risk:register:*"):
            raw = await self._store.get(key)
            if not raw:
                continue
            record = _record_from_dict(raw)
            rating = record.risk.residual_rating or record.risk.inherent_rating
            buckets[rating.value] += 1
        return buckets

    async def dashboard(self) -> dict[str, Any]:
        counts_by_state: dict[str, int] = {s.value: 0 for s in RiskState}
        total = 0
        for key in await self._store.keys("risk:register:*"):
            raw = await self._store.get(key)
            if not raw:
                continue
            record = _record_from_dict(raw)
            counts_by_state[record.state.state.value] += 1
            total += 1
        return {
            "total_risks": total,
            "by_state": counts_by_state,
            "by_rating": await self.heat_map(),
        }

    async def _emit(self, event: AuditEvent, record: RiskRecord, *, reason: str) -> None:
        if self._audit is None:
            return
        await self._audit.emit(
            AuditRecord(
                tenant_id=record.risk.tenant_id,
                event_type=event.value,
                persona="risk",
                extra={
                    "risk_id": record.risk.risk_id,
                    "state": record.state.state.value,
                    "rating": (record.risk.residual_rating or record.risk.inherent_rating).value,
                    "reason": reason,
                },
            )
        )

    def _publish_score(self, record: RiskRecord) -> None:
        rating = record.risk.residual_rating or record.risk.inherent_rating
        numeric = {"low": 1.0, "medium": 2.0, "high": 3.0, "critical": 4.0}[rating.value]
        try:
            get_metrics().risk_score.labels(
                category=record.risk.category.value,
                tenant=tenant_label(record.risk.tenant_id),
            ).set(numeric)
        except Exception:
            pass


# ----- serialisation ------------------------------------------------------


def _record_to_dict(record: RiskRecord) -> dict[str, Any]:
    risk = record.risk
    return {
        "risk": {
            "risk_id": risk.risk_id,
            "title": risk.title,
            "description": risk.description,
            "category": risk.category.value,
            "tenant_id": risk.tenant_id,
            "inherent_likelihood": int(risk.inherent_likelihood),
            "inherent_impact": int(risk.inherent_impact),
            "residual_likelihood": int(risk.residual_likelihood) if risk.residual_likelihood else None,
            "residual_impact": int(risk.residual_impact) if risk.residual_impact else None,
            "treatment": (
                {
                    "type": risk.treatment.type,
                    "description": risk.treatment.description,
                    "owner": risk.treatment.owner,
                    "due_date": risk.treatment.due_date,
                    "controls": list(risk.treatment.controls),
                }
                if risk.treatment
                else None
            ),
            "linked_kris": list(risk.linked_kris),
            "owner": risk.owner,
            "created_at": risk.created_at,
            "metadata": dict(risk.metadata),
        },
        "state": record.state.state.value,
        "history": [
            {
                "from": t.from_state.value,
                "to": t.to_state.value,
                "timestamp": t.timestamp,
                "actor": t.actor,
                "reason": t.reason,
                "metadata": dict(t.metadata),
            }
            for t in record.state.history
        ],
    }


def _record_from_dict(raw: dict[str, Any]) -> RiskRecord:
    r = raw["risk"]
    treatment_raw = r.get("treatment")
    treatment = (
        RiskTreatment(
            type=treatment_raw.get("type", "mitigate"),
            description=treatment_raw.get("description", ""),
            owner=treatment_raw.get("owner", ""),
            due_date=treatment_raw.get("due_date"),
            controls=list(treatment_raw.get("controls", [])),
        )
        if treatment_raw
        else None
    )
    risk = Risk(
        risk_id=r["risk_id"],
        title=r["title"],
        description=r.get("description", ""),
        category=RiskCategory(r.get("category", RiskCategory.OPERATIONAL.value)),
        tenant_id=r.get("tenant_id"),
        inherent_likelihood=Likelihood(r.get("inherent_likelihood", Likelihood.POSSIBLE.value)),
        inherent_impact=Impact(r.get("inherent_impact", Impact.MODERATE.value)),
        residual_likelihood=Likelihood(r["residual_likelihood"]) if r.get("residual_likelihood") else None,
        residual_impact=Impact(r["residual_impact"]) if r.get("residual_impact") else None,
        treatment=treatment,
        linked_kris=list(r.get("linked_kris", [])),
        owner=r.get("owner", ""),
        created_at=r.get("created_at", datetime.now(timezone.utc).isoformat()),
        metadata=dict(r.get("metadata", {})),
    )
    state: StatefulRecord[RiskState] = StatefulRecord(state=RiskState(raw.get("state", RiskState.IDENTIFIED.value)))
    # History is reconstructed read-only for audit; we don't replay transitions.
    return RiskRecord(risk=risk, state=state)


__all__ = [
    "RISK_TRANSITIONS",
    "Impact",
    "Likelihood",
    "Risk",
    "RiskCategory",
    "RiskRating",
    "RiskRecord",
    "RiskRegister",
    "RiskState",
    "RiskTreatment",
]
