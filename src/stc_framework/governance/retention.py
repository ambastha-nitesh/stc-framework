"""Retention enforcement with per-event-class policies.

Different classes of audit records have different regulatory retention
windows:

- generic query audit: 365 days (spec default)
- erasure receipts / DSAR exports: 6 years (GDPR evidence)
- boundary crossings / data-sovereignty violations: 6 years
- escalation transitions: 6 years (SOC 2 / NYDFS)
- chain seals (rotation, retention prune): forever (they glue the
  audit hash chain together)

A single ``audit.retention_days`` knob would delete any of the above
after 1 year. This implementation walks the audit backend and keeps
whichever record has any *still-in-window* retention — the record is
deleted only when every applicable policy agrees it's expired.

Because the default JSONL backend only supports file-granularity
pruning, we prune a file only when *every* record inside is past its
class-specific cutoff. WORM backends reject the prune call entirely,
as they should.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class RetentionSummary:
    retention_days: int
    audit_removed: int = 0
    history_removed: int = 0
    tokens_removed: int = 0


async def apply_retention(system: Any) -> RetentionSummary:
    """Apply retention to every store that supports it."""
    from stc_framework.governance.events import AuditEvent
    from stc_framework.observability.audit import AuditRecord

    audit_spec = system.spec.audit
    default_days = audit_spec.retention_days
    policies = audit_spec.retention_policies
    now = datetime.now(timezone.utc)

    summary = RetentionSummary(retention_days=default_days)

    # Audit backend — use class-specific cutoff if supported, else the
    # legacy flat cutoff.
    audit = getattr(system, "_audit", None)
    if audit is not None:
        backend = audit.backend
        prune_fn = getattr(backend, "prune_before", None)
        if callable(prune_fn):
            # Effective cutoff = the OLDEST (most distant past) cutoff
            # across all configured classes. Any record sitting in a
            # file whose youngest record is older than this cutoff is
            # safe to delete for every class — so the file can go.
            # Iterate over declared model fields only — avoids Pydantic
            # deprecation warnings from instance-level dir() inspection.
            days_list = [
                getattr(policies, name)
                for name in type(policies).model_fields
                if isinstance(getattr(policies, name), int)
            ]
            retained_forever = any(d < 0 for d in days_list)
            if retained_forever:
                # If any class is "forever", files that might contain
                # such records must not be pruned. We conservatively
                # skip pruning entirely — the operator should use the
                # WORM backend for this use case.
                summary.audit_removed = 0
            else:
                max_days = max(days_list) if days_list else default_days
                cutoff = (now - timedelta(days=max_days)).isoformat()
                try:
                    summary.audit_removed = prune_fn(cutoff)
                except NotImplementedError:  # pragma: no cover
                    pass
                except Exception:
                    # WORM backend: ComplianceViolation — swallow so
                    # retention sweep reports 0 for the audit tier.
                    summary.audit_removed = 0

    history = getattr(getattr(system, "trainer", None), "history", None)
    prune_history = getattr(history, "prune_before", None)
    if callable(prune_history):
        history_cutoff = now - timedelta(days=default_days)
        try:
            summary.history_removed = prune_history(history_cutoff)
        except Exception:  # pragma: no cover
            pass

    gateway = getattr(system, "gateway", None)
    tokenizer = getattr(gateway, "_tokenizer", None)
    if tokenizer is not None:
        store = getattr(tokenizer, "_store", None)
        prune_tokens = getattr(store, "prune_before", None)
        if callable(prune_tokens):
            token_cutoff = now - timedelta(days=default_days)
            try:
                summary.tokens_removed = prune_tokens(token_cutoff)
            except Exception:  # pragma: no cover
                pass

    if audit is not None:
        await audit.emit(
            AuditRecord(
                tenant_id=None,
                persona="governance",
                event_type=AuditEvent.RETENTION_SWEEP.value,
                action="pruned",
                extra={
                    "retention_days_default": default_days,
                    "audit_removed": summary.audit_removed,
                    "history_removed": summary.history_removed,
                    "tokens_removed": summary.tokens_removed,
                },
            )
        )

    return summary
