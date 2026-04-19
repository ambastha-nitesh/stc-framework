"""NYDFS 23 NYCRR 500 — 72-hour cybersecurity incident notification.

Part 500 requires covered entities to notify the Superintendent of
Financial Services within 72 hours of a "cybersecurity event that is
required to be reported." This module manages the full workflow:

1. ``create_notification`` — draft on incident detection; clock starts.
2. ``approve`` — CISO (or delegate) signs off on the draft.
3. ``submit`` — the notification is filed with NYDFS (stubbed; the
   filing channel is out of scope — this module just marks it).
4. ``check_deadlines`` — escalates AMBER at <24h remaining, RED at <4h.

Deadlines use :class:`stc_framework._internal.alerter.Thresholds` so
status classification matches the rest of the framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from stc_framework._internal.alerter import AlertLevel, Thresholds
from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord


class NotificationStatus(str, Enum):
    DRAFTED = "drafted"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    OVERDUE = "overdue"


# Hours remaining where amber/red trip.
_DEADLINE_THRESHOLDS = Thresholds(amber=24.0, red=4.0, direction="lower_is_worse")


@dataclass
class IncidentNotification:
    notification_id: str
    incident_id: str
    severity: str = "high"
    status: NotificationStatus = NotificationStatus.DRAFTED
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    deadline: str = ""
    approver: str = ""
    submitted_at: str = ""
    body: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def hours_remaining(self, *, now: datetime | None = None) -> float:
        if not self.deadline:
            return 72.0
        current = now or datetime.now(timezone.utc)
        end = datetime.fromisoformat(self.deadline.replace("Z", "+00:00"))
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        delta = (end - current).total_seconds() / 3600
        return max(0.0, delta)

    def deadline_status(self, *, now: datetime | None = None) -> AlertLevel:
        return _DEADLINE_THRESHOLDS.classify(self.hours_remaining(now=now))


_KEY = "compliance:nydfs:notif:{notification_id}"


class NYDFSNotificationEngine:
    """Lifecycle + deadline manager for 72-hour NYDFS notifications."""

    def __init__(self, store: KeyValueStore, *, audit: AuditLogger | None = None) -> None:
        self._store = store
        self._audit = audit

    async def create_notification(
        self,
        *,
        notification_id: str,
        incident_id: str,
        severity: str = "high",
        body: str = "",
    ) -> IncidentNotification:
        now = datetime.now(timezone.utc)
        deadline = (now + timedelta(hours=72)).isoformat()
        notif = IncidentNotification(
            notification_id=notification_id,
            incident_id=incident_id,
            severity=severity,
            status=NotificationStatus.PENDING_APPROVAL,
            discovered_at=now.isoformat(),
            deadline=deadline,
            body=body,
        )
        await self._store.set(_KEY.format(notification_id=notification_id), _to_dict(notif))
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.COMPLIANCE_CHECK_EVALUATED.value,
                    persona="compliance",
                    extra={"rule": "nydfs_500", "action": "created", "id": notification_id},
                )
            )
        return notif

    async def approve(self, notification_id: str, *, approver: str) -> IncidentNotification:
        raw = await self._store.get(_KEY.format(notification_id=notification_id))
        if not raw:
            raise KeyError(notification_id)
        raw["status"] = NotificationStatus.APPROVED.value
        raw["approver"] = approver
        await self._store.set(_KEY.format(notification_id=notification_id), raw)
        return _from_dict(raw)

    async def submit(self, notification_id: str) -> IncidentNotification:
        raw = await self._store.get(_KEY.format(notification_id=notification_id))
        if not raw:
            raise KeyError(notification_id)
        raw["status"] = NotificationStatus.SUBMITTED.value
        raw["submitted_at"] = datetime.now(timezone.utc).isoformat()
        await self._store.set(_KEY.format(notification_id=notification_id), raw)
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.COMPLIANCE_CHECK_EVALUATED.value,
                    persona="compliance",
                    extra={"rule": "nydfs_500", "action": "submitted", "id": notification_id},
                )
            )
        return _from_dict(raw)

    async def check_deadlines(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        keys = await self._store.keys("compliance:nydfs:notif:*")
        for k in keys:
            raw = await self._store.get(k)
            if not raw:
                continue
            notif = _from_dict(raw)
            if notif.status in (
                NotificationStatus.SUBMITTED,
                NotificationStatus.ACKNOWLEDGED,
            ):
                continue
            hours = notif.hours_remaining(now=now)
            level = notif.deadline_status(now=now)
            if hours <= 0 and notif.status is not NotificationStatus.OVERDUE:
                raw["status"] = NotificationStatus.OVERDUE.value
                await self._store.set(k, raw)
            out.append(
                {
                    "notification_id": notif.notification_id,
                    "hours_remaining": hours,
                    "level": level.value,
                    "status": raw["status"],
                }
            )
        return out

    async def dashboard(self) -> dict[str, Any]:
        items = await self.check_deadlines()
        return {
            "count": len(items),
            "overdue": [i for i in items if i["status"] == NotificationStatus.OVERDUE.value],
            "red": [i for i in items if i["level"] == "red"],
            "amber": [i for i in items if i["level"] == "amber"],
        }


def _to_dict(n: IncidentNotification) -> dict[str, Any]:
    return {
        "notification_id": n.notification_id,
        "incident_id": n.incident_id,
        "severity": n.severity,
        "status": n.status.value,
        "discovered_at": n.discovered_at,
        "deadline": n.deadline,
        "approver": n.approver,
        "submitted_at": n.submitted_at,
        "body": n.body,
        "metadata": dict(n.metadata),
    }


def _from_dict(raw: dict[str, Any]) -> IncidentNotification:
    return IncidentNotification(
        notification_id=raw["notification_id"],
        incident_id=raw["incident_id"],
        severity=raw.get("severity", "high"),
        status=NotificationStatus(raw.get("status", NotificationStatus.DRAFTED.value)),
        discovered_at=raw.get("discovered_at", ""),
        deadline=raw.get("deadline", ""),
        approver=raw.get("approver", ""),
        submitted_at=raw.get("submitted_at", ""),
        body=raw.get("body", ""),
        metadata=dict(raw.get("metadata", {})),
    )


__all__ = ["IncidentNotification", "NYDFSNotificationEngine", "NotificationStatus"]
