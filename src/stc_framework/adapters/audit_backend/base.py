"""Audit backend protocol."""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable

from stc_framework.observability.audit import AuditRecord


@runtime_checkable
class AuditBackend(Protocol):
    """Append-only storage for :class:`AuditRecord`.

    Implementations are expected to preserve write order, compute the
    ``entry_hash`` / ``prev_hash`` chain, and expose read helpers that
    governance workflows (DSAR, retention, verification) can use.
    """

    async def append(self, record: AuditRecord) -> AuditRecord: ...

    def append_sync(self, record: AuditRecord) -> AuditRecord: ...

    async def close(self) -> None: ...

    # ---- read / iterate (used by DSAR, retention, verification) -----
    def iter_records(self) -> Iterator[AuditRecord]:
        """Yield records in append order."""
        raise NotImplementedError

    def iter_for_tenant(self, tenant_id: str) -> Iterator[AuditRecord]:
        for rec in self.iter_records():
            if rec.tenant_id == tenant_id:
                yield rec

    def prune_before(self, cutoff_iso: str) -> int:  # pragma: no cover - default
        """Delete records older than ``cutoff_iso``. Returns count removed.

        Default implementation raises; backends that support retention
        must override.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support retention pruning"
        )

    def erase_tenant(self, tenant_id: str) -> int:  # pragma: no cover - default
        """Delete records for ``tenant_id``. Returns count removed."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support tenant erasure"
        )
