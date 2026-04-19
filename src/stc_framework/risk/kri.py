"""Key Risk Indicator engine.

Ingests periodic KRI measurements, classifies each into GREEN / AMBER /
RED, and auto-escalates linked risks when an indicator flips to RED.
Emits ``KRI_RECORDED`` on every measurement and ``KRI_BREACH`` on RED
transitions.

The default catalog ships with 12 indicators covering accuracy,
hallucination rate, PII incidents, sovereignty violations, budget
saturation, latency, and availability — the ones that fell out of the
experimental module. Callers can register additional KRIs at runtime.

State is persisted through the KeyValueStore so dashboards surviving
process restarts work out of the box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stc_framework._internal.alerter import AlertLevel, Thresholds
from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.metrics import get_metrics


class KRIStatus(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"

    @classmethod
    def from_alert(cls, level: AlertLevel) -> KRIStatus:
        return cls(level.value)

    @property
    def numeric(self) -> int:
        return {KRIStatus.GREEN: 0, KRIStatus.AMBER: 1, KRIStatus.RED: 2}[self]


@dataclass
class KRIDefinition:
    """Configuration for a single indicator."""

    kri_id: str
    name: str
    direction: str = "higher_is_worse"
    amber: float = 0.0
    red: float = 0.0
    linked_risks: list[str] = field(default_factory=list)
    description: str = ""

    @property
    def thresholds(self) -> Thresholds:
        return Thresholds(amber=self.amber, red=self.red, direction=self.direction)


@dataclass
class KRIMeasurement:
    kri_id: str
    value: float
    status: KRIStatus
    recorded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


# Default KRI catalog. Mirrors experimental/risk/risk_register.py DEFAULT_KRIS
# but uses v0.3.0 threshold semantics (explicit amber/red values, direction
# attribute). Callers can override via register().
DEFAULT_KRIS: list[KRIDefinition] = [
    KRIDefinition(
        kri_id="accuracy_rate",
        name="Agent response accuracy",
        direction="lower_is_worse",
        amber=0.90,
        red=0.80,
        linked_risks=["risk-accuracy-drop"],
    ),
    KRIDefinition(
        kri_id="hallucination_rate",
        name="Hallucination detection rate",
        direction="higher_is_worse",
        amber=0.05,
        red=0.10,
        linked_risks=["risk-hallucination"],
    ),
    KRIDefinition(
        kri_id="pii_leak_rate",
        name="PII redaction misses per 1k",
        direction="higher_is_worse",
        amber=0.5,
        red=2.0,
        linked_risks=["risk-pii-leak"],
    ),
    KRIDefinition(
        kri_id="sovereignty_violations",
        name="Boundary crossings to disallowed model",
        direction="higher_is_worse",
        amber=1.0,
        red=5.0,
        linked_risks=["risk-sovereignty"],
    ),
    KRIDefinition(
        kri_id="budget_saturation",
        name="Daily budget consumed (%)",
        direction="higher_is_worse",
        amber=80.0,
        red=95.0,
        linked_risks=["risk-runaway-cost"],
    ),
    KRIDefinition(
        kri_id="latency_p95_ms",
        name="p95 end-to-end latency",
        direction="higher_is_worse",
        amber=2000.0,
        red=5000.0,
        linked_risks=["risk-latency"],
    ),
    KRIDefinition(
        kri_id="availability",
        name="System availability",
        direction="lower_is_worse",
        amber=0.995,
        red=0.99,
        linked_risks=["risk-availability"],
    ),
    KRIDefinition(
        kri_id="guardrail_failure_rate",
        name="Output-rail failure rate",
        direction="higher_is_worse",
        amber=0.05,
        red=0.15,
        linked_risks=["risk-guardrail"],
    ),
    KRIDefinition(
        kri_id="critic_escalation_rate",
        name="Critic escalations per 1k queries",
        direction="higher_is_worse",
        amber=5.0,
        red=20.0,
        linked_risks=["risk-critic-overload"],
    ),
    KRIDefinition(
        kri_id="queue_depth",
        name="Bulkhead queue depth",
        direction="higher_is_worse",
        amber=50.0,
        red=200.0,
        linked_risks=["risk-capacity"],
    ),
    KRIDefinition(
        kri_id="vendor_concentration",
        name="Single-vendor traffic share",
        direction="higher_is_worse",
        amber=0.80,
        red=0.95,
        linked_risks=["risk-vendor-lock"],
    ),
    KRIDefinition(
        kri_id="model_drift_score",
        name="Model embedding drift",
        direction="higher_is_worse",
        amber=0.2,
        red=0.4,
        linked_risks=["risk-model-drift"],
    ),
]


_KEY_KRI_DEF = "risk:kri:def:{kri_id}"
_KEY_KRI_LATEST = "risk:kri:latest:{kri_id}"


class KRIEngine:
    """Ingests KRI measurements and escalates linked risks when RED."""

    def __init__(
        self,
        store: KeyValueStore,
        *,
        audit: AuditLogger | None = None,
        escalate_callback: Any = None,  # async callable: (kri_id, linked_risks) -> None
    ) -> None:
        self._store = store
        self._audit = audit
        self._escalate = escalate_callback
        self._definitions: dict[str, KRIDefinition] = {}

    async def bootstrap_defaults(self) -> None:
        for kri in DEFAULT_KRIS:
            await self.register(kri)

    async def register(self, kri: KRIDefinition) -> None:
        self._definitions[kri.kri_id] = kri
        await self._store.set(
            _KEY_KRI_DEF.format(kri_id=kri.kri_id),
            {
                "kri_id": kri.kri_id,
                "name": kri.name,
                "direction": kri.direction,
                "amber": kri.amber,
                "red": kri.red,
                "linked_risks": list(kri.linked_risks),
                "description": kri.description,
            },
        )

    async def record(self, kri_id: str, value: float) -> KRIMeasurement:
        kri = self._definitions.get(kri_id)
        if kri is None:
            # Fetch from store as a fallback — supports multi-process deployments
            raw = await self._store.get(_KEY_KRI_DEF.format(kri_id=kri_id))
            if raw is None:
                raise KeyError(f"unknown KRI {kri_id!r}")
            kri = KRIDefinition(
                kri_id=raw["kri_id"],
                name=raw.get("name", kri_id),
                direction=raw.get("direction", "higher_is_worse"),
                amber=float(raw["amber"]),
                red=float(raw["red"]),
                linked_risks=list(raw.get("linked_risks", [])),
                description=raw.get("description", ""),
            )
            self._definitions[kri_id] = kri

        level = kri.thresholds.classify(value)
        status = KRIStatus.from_alert(level)
        measurement = KRIMeasurement(kri_id=kri_id, value=value, status=status)
        await self._store.set(
            _KEY_KRI_LATEST.format(kri_id=kri_id),
            {"value": value, "status": status.value, "recorded_at": measurement.recorded_at},
        )
        self._publish_status_metric(kri_id, status)
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.KRI_RECORDED.value,
                    persona="risk",
                    extra={"kri_id": kri_id, "value": value, "status": status.value},
                )
            )
        if status is KRIStatus.RED:
            await self._on_red(kri, value)
        return measurement

    async def latest(self, kri_id: str) -> KRIMeasurement | None:
        raw = await self._store.get(_KEY_KRI_LATEST.format(kri_id=kri_id))
        if raw is None:
            return None
        return KRIMeasurement(
            kri_id=kri_id,
            value=float(raw["value"]),
            status=KRIStatus(raw["status"]),
            recorded_at=raw.get("recorded_at", datetime.now(timezone.utc).isoformat()),
        )

    async def dashboard(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for kri_id in self._definitions:
            latest = await self.latest(kri_id)
            out[kri_id] = {
                "status": latest.status.value if latest else "unknown",
                "value": latest.value if latest else None,
                "recorded_at": latest.recorded_at if latest else None,
            }
        return out

    async def any_red(self) -> list[str]:
        red_ids: list[str] = []
        for kri_id in self._definitions:
            latest = await self.latest(kri_id)
            if latest and latest.status is KRIStatus.RED:
                red_ids.append(kri_id)
        return red_ids

    async def _on_red(self, kri: KRIDefinition, value: float) -> None:
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.KRI_BREACH.value,
                    persona="risk",
                    action="red",
                    extra={
                        "kri_id": kri.kri_id,
                        "value": value,
                        "red_threshold": kri.red,
                        "linked_risks": list(kri.linked_risks),
                    },
                )
            )
        if self._escalate is not None:
            # Caller-supplied async; escalate linked risks. Missing ids are ignored.
            for risk_id in kri.linked_risks:
                try:
                    await self._escalate(kri.kri_id, risk_id)
                except KeyError:
                    # Risk not in the register — best-effort, don't crash the KRI pipeline.
                    continue

    def _publish_status_metric(self, kri_id: str, status: KRIStatus) -> None:
        try:
            get_metrics().kri_status.labels(kri_id=kri_id).set(float(status.numeric))
        except Exception:
            pass


__all__ = ["DEFAULT_KRIS", "KRIDefinition", "KRIEngine", "KRIMeasurement", "KRIStatus"]
