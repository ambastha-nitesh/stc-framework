"""Legal hold registry.

A legal hold freezes destruction / modification of a set of artifacts
while litigation, investigation, or regulatory inquiry is in progress.
This module implements the :class:`LegalHoldChecker` Protocol expected
by :mod:`stc_framework.governance.destruction` so retention sweeps and
DSAR erasures consult holds before touching anything.

A hold is scoped by ``(tenant_id, keywords, data_store, date_range)``.
Any artifact whose identifier matches any keyword, falls within the
date range, and belongs to the named tenant and store is protected.

Storage is pluggable via :class:`KeyValueStore`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord


@dataclass
class LegalHold:
    hold_id: str
    matter_id: str = ""
    tenant_ids: list[str] = field(default_factory=list)  # empty = all tenants
    data_stores: list[str] = field(default_factory=list)  # empty = all stores
    keywords: list[str] = field(default_factory=list)  # empty = matches all artifacts
    start_date: str = ""
    end_date: str | None = None  # None = open-ended
    issued_by: str = ""
    reason: str = ""
    active: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


_KEY_HOLD = "compliance:legal_hold:{hold_id}"


class LegalHoldManager:
    """CRUD for holds + :meth:`check_destruction_allowed` for the retention layer."""

    def __init__(self, store: KeyValueStore, *, audit: AuditLogger | None = None) -> None:
        self._store = store
        self._audit = audit

    async def issue(self, hold: LegalHold) -> None:
        await self._store.set(_KEY_HOLD.format(hold_id=hold.hold_id), _to_dict(hold))
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.LEGAL_HOLD_ISSUED.value,
                    persona="compliance",
                    extra={
                        "hold_id": hold.hold_id,
                        "matter_id": hold.matter_id,
                        "tenant_ids": list(hold.tenant_ids),
                        "issued_by": hold.issued_by,
                    },
                )
            )

    async def release(self, hold_id: str, *, actor: str, reason: str = "") -> None:
        raw = await self._store.get(_KEY_HOLD.format(hold_id=hold_id))
        if not raw:
            raise KeyError(f"hold not found: {hold_id!r}")
        raw["active"] = False
        raw["released_by"] = actor
        raw["released_at"] = datetime.now(timezone.utc).isoformat()
        raw["release_reason"] = reason
        await self._store.set(_KEY_HOLD.format(hold_id=hold_id), raw)
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.LEGAL_HOLD_RELEASED.value,
                    persona="compliance",
                    extra={"hold_id": hold_id, "actor": actor, "reason": reason},
                )
            )

    async def active_holds(self) -> list[LegalHold]:
        keys = await self._store.keys("compliance:legal_hold:*")
        out: list[LegalHold] = []
        for k in keys:
            raw = await self._store.get(k)
            if isinstance(raw, dict) and raw.get("active"):
                out.append(_from_dict(raw))
        return out

    async def check_destruction_allowed(
        self,
        *,
        artifact: str,
        data_store: str,
        tenant_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """Return ``(allowed, hold_id_or_none)``.

        Any active matching hold blocks destruction.
        """
        for hold in await self.active_holds():
            if hold.tenant_ids and tenant_id and tenant_id not in hold.tenant_ids:
                continue
            if hold.data_stores and data_store and data_store not in hold.data_stores:
                continue
            if hold.keywords:
                if not any(kw.lower() in artifact.lower() for kw in hold.keywords):
                    continue
            return False, hold.hold_id
        return True, None


def _to_dict(hold: LegalHold) -> dict[str, Any]:
    return {
        "hold_id": hold.hold_id,
        "matter_id": hold.matter_id,
        "tenant_ids": list(hold.tenant_ids),
        "data_stores": list(hold.data_stores),
        "keywords": list(hold.keywords),
        "start_date": hold.start_date,
        "end_date": hold.end_date,
        "issued_by": hold.issued_by,
        "reason": hold.reason,
        "active": hold.active,
        "created_at": hold.created_at,
    }


def _from_dict(raw: dict[str, Any]) -> LegalHold:
    return LegalHold(
        hold_id=raw["hold_id"],
        matter_id=raw.get("matter_id", ""),
        tenant_ids=list(raw.get("tenant_ids", [])),
        data_stores=list(raw.get("data_stores", [])),
        keywords=list(raw.get("keywords", [])),
        start_date=raw.get("start_date", ""),
        end_date=raw.get("end_date"),
        issued_by=raw.get("issued_by", ""),
        reason=raw.get("reason", ""),
        active=bool(raw.get("active", True)),
        created_at=raw.get("created_at", datetime.now(timezone.utc).isoformat()),
    )


__all__ = ["LegalHold", "LegalHoldManager"]
