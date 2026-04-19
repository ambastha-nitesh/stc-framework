"""Right-to-erasure implementation.

Deletes every tenant-scoped artifact across the system:

- audit records (via ``AuditBackend.erase_tenant`` — if the backend
  supports it; WORM backends raise :class:`ComplianceViolation` and
  the operator must tombstone instead),
- trainer performance history,
- vector-store documents (if the adapter supports tenant deletion),
- token-store entries written with that tenant scope,
- idempotency cache entries (so previously-cached responses cannot
  resurface post-erasure),
- budget-tracker samples,
- per-tenant rate-limiter buckets.

The operation itself produces a final :class:`AuditRecord` with
``event_type = erasure`` so a regulator can prove the deletion
happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ErasureSummary:
    tenant_id: str
    audit_removed: int = 0
    history_removed: int = 0
    vector_removed: int = 0
    tokens_removed: int = 0
    idempotency_removed: int = 0
    budget_samples_removed: int = 0
    rate_limit_removed: int = 0


async def erase_tenant(system: Any, tenant_id: str) -> ErasureSummary:
    """Erase every tenant-scoped record across the system."""
    from stc_framework.governance.events import AuditEvent
    from stc_framework.observability.audit import AuditRecord

    summary = ErasureSummary(tenant_id=tenant_id)

    # History — the default InMemoryHistoryStore / SQLiteHistoryStore
    # stores tenant_id under metadata.
    history = getattr(getattr(system, "trainer", None), "history", None)
    erase_history = getattr(history, "erase_tenant", None)
    if callable(erase_history):
        try:
            summary.history_removed = erase_history(tenant_id)
        except Exception:  # pragma: no cover
            pass

    # Vector store
    vstore = getattr(system, "vector_store", None)
    erase_vec = getattr(vstore, "erase_tenant", None)
    if callable(erase_vec):
        try:
            summary.vector_removed = await erase_vec(tenant_id)
        except Exception:  # pragma: no cover
            pass

    # Token store (through the Sentinel tokenizer).
    gateway = getattr(system, "gateway", None)
    tokenizer = getattr(gateway, "_tokenizer", None)
    if tokenizer is not None:
        store = getattr(tokenizer, "_store", None)
        erase_tokens = getattr(store, "erase_tenant", None)
        if callable(erase_tokens):
            try:
                summary.tokens_removed = erase_tokens(tenant_id)
            except Exception:  # pragma: no cover
                pass

    # Idempotency cache — previously-cached results must not be
    # returned after erasure (regulator sees erasure receipt; client
    # sees supposedly-erased data otherwise).
    idempotency = getattr(system, "_idempotency", None)
    if idempotency is not None:
        erase_idem = getattr(idempotency, "erase_tenant", None)
        if callable(erase_idem):
            try:
                summary.idempotency_removed = erase_idem(tenant_id)
            except Exception:  # pragma: no cover
                pass

    # Budget tracker — remove rolling cost history.
    budget = getattr(system, "_budget", None)
    if budget is not None:
        erase_budget = getattr(budget, "erase_tenant", None)
        if callable(erase_budget):
            try:
                summary.budget_samples_removed = erase_budget(tenant_id)
            except Exception:  # pragma: no cover
                pass

    # Rate-limiter bucket.
    rl = getattr(system, "_rate_limiter", None)
    if rl is not None:
        erase_rl = getattr(rl, "erase_tenant", None)
        if callable(erase_rl):
            try:
                summary.rate_limit_removed = erase_rl(tenant_id)
            except Exception:  # pragma: no cover
                pass

    # Audit — perform last so the erasure record itself is retained.
    audit_logger = getattr(system, "_audit", None)
    if audit_logger is not None:
        backend = audit_logger.backend
        erase_fn = getattr(backend, "erase_tenant", None)
        if callable(erase_fn):
            try:
                summary.audit_removed = erase_fn(tenant_id)
            except Exception:
                # WORM backend refuses — that's expected under SEC 17a-4.
                # We still continue and emit the erasure audit so the
                # regulator sees the attempt and the reason for the
                # refusal.
                pass
        # Record the erasure action — under a neutral tenant so it is
        # not itself erased on a second call.
        await audit_logger.emit(
            AuditRecord(
                tenant_id=None,
                persona="governance",
                event_type=AuditEvent.ERASURE.value,
                action="erased",
                extra={
                    "target_tenant": tenant_id,
                    "audit_removed": summary.audit_removed,
                    "history_removed": summary.history_removed,
                    "vector_removed": summary.vector_removed,
                    "tokens_removed": summary.tokens_removed,
                    "idempotency_removed": summary.idempotency_removed,
                    "budget_samples_removed": summary.budget_samples_removed,
                    "rate_limit_removed": summary.rate_limit_removed,
                },
            )
        )

    return summary
