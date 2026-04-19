"""Data Subject Access Request (DSAR) helper.

Walks every store that can hold a tenant's data and returns a single,
structured record. Used both by the Flask service's DSAR endpoint and by
ad-hoc compliance exports.

Every DSAR export also emits an audit entry of its own so the regulator
can prove the request was served.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class DSARRecord:
    """Aggregated view of everything a tenant has touched in the system."""

    tenant_id: str
    exported_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    audit_records: list[dict[str, Any]] = field(default_factory=list)
    history_records: list[dict[str, Any]] = field(default_factory=list)
    vector_documents: list[dict[str, Any]] = field(default_factory=list)
    prompt_registrations: list[dict[str, Any]] = field(default_factory=list)


async def export_tenant_records(system: Any, tenant_id: str) -> DSARRecord:
    """Build a :class:`DSARRecord` for ``tenant_id`` from ``system``.

    The walk is best-effort — if an optional store is not wired, it is
    skipped rather than failing the whole export.
    """
    from stc_framework.governance.events import AuditEvent
    from stc_framework.observability.audit import AuditRecord

    record = DSARRecord(tenant_id=tenant_id)

    # 1. Audit log
    backend = getattr(getattr(system, "_audit", None), "backend", None)
    if backend is not None:
        try:
            for entry in backend.iter_for_tenant(tenant_id):
                record.audit_records.append(entry.model_dump())
        except Exception:  # pragma: no cover
            pass

    # 2. Performance history (trainer)
    history = getattr(getattr(system, "trainer", None), "history", None)
    if history is not None:
        try:
            for h in history.all():
                if h.metadata.get("tenant_id") == tenant_id:
                    record.history_records.append(
                        {
                            "trace_id": h.trace_id,
                            "timestamp": h.timestamp,
                            "accuracy": h.accuracy,
                            "cost_usd": h.cost_usd,
                            "latency_ms": h.latency_ms,
                        }
                    )
        except Exception:  # pragma: no cover
            pass

    # 3. Vector store — only if the adapter exposes a tenant filter.
    vstore = getattr(system, "vector_store", None)
    list_fn = getattr(vstore, "list_for_tenant", None)
    if callable(list_fn):
        try:
            record.vector_documents = await list_fn(tenant_id)
        except Exception:  # pragma: no cover
            pass

    # 4. Audit the export itself.
    audit = getattr(system, "_audit", None)
    if audit is not None:
        await audit.emit(
            AuditRecord(
                tenant_id=tenant_id,
                persona="governance",
                event_type=AuditEvent.DSAR_EXPORT.value,
                action="export",
                extra={
                    "audit_count": len(record.audit_records),
                    "history_count": len(record.history_records),
                    "vector_count": len(record.vector_documents),
                },
            )
        )

    return record
