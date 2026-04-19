"""AI transparency & consent.

Two concerns bundled because they travel together:

* **Disclosure application** — prepends/appends a required disclosure
  to AI-generated client-facing output (SEC-style "AI was used to
  generate this response").
* **Consent registry** — records whether a customer has consented to
  AI-generated interactions, keyed by ``(tenant_id, customer_id)``.
  Callers check before producing AI output for a specific customer.

Both use :class:`KeyValueStore` for persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord

DEFAULT_DISCLOSURE = (
    "This response was generated with the assistance of an AI system. "
    "It is for informational purposes only and does not constitute investment advice."
)


@dataclass
class ConsentRecord:
    customer_id: str
    tenant_id: str
    consented: bool
    consented_at: str = ""
    revoked_at: str | None = None
    version: str = "v1"


_KEY = "compliance:consent:{tenant_id}:{customer_id}"


class TransparencyManager:
    def __init__(
        self,
        store: KeyValueStore,
        *,
        audit: AuditLogger | None = None,
        disclosure_text: str = DEFAULT_DISCLOSURE,
    ) -> None:
        self._store = store
        self._audit = audit
        self._disclosure = disclosure_text

    def apply_disclosure(self, content: str, *, inline: bool = False) -> str:
        """Return ``content`` with disclosure appended (or prepended if inline=False)."""
        if self._disclosure in content:
            return content  # idempotent — don't double-stamp
        return f"{content}\n\n— {self._disclosure}" if not inline else f"{self._disclosure}\n\n{content}"

    async def record_consent(
        self,
        *,
        tenant_id: str,
        customer_id: str,
        consented: bool,
        version: str = "v1",
    ) -> ConsentRecord:
        record = ConsentRecord(
            customer_id=customer_id,
            tenant_id=tenant_id,
            consented=consented,
            consented_at=datetime.now(timezone.utc).isoformat() if consented else "",
            revoked_at=datetime.now(timezone.utc).isoformat() if not consented else None,
            version=version,
        )
        await self._store.set(
            _KEY.format(tenant_id=tenant_id, customer_id=customer_id),
            {
                "customer_id": customer_id,
                "tenant_id": tenant_id,
                "consented": consented,
                "consented_at": record.consented_at,
                "revoked_at": record.revoked_at,
                "version": version,
            },
        )
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    tenant_id=tenant_id,
                    event_type=AuditEvent.CONSENT_RECORDED.value,
                    persona="compliance",
                    extra={"customer_id": customer_id, "consented": consented, "version": version},
                )
            )
        return record

    async def check_consent(self, *, tenant_id: str, customer_id: str) -> bool:
        raw = await self._store.get(_KEY.format(tenant_id=tenant_id, customer_id=customer_id))
        return bool(raw and raw.get("consented"))

    async def emit_disclosure_audit(self, *, tenant_id: str, applied_to: str) -> None:
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    tenant_id=tenant_id,
                    event_type=AuditEvent.DISCLOSURE_APPLIED.value,
                    persona="compliance",
                    extra={"applied_to": applied_to},
                )
            )

    async def report(self) -> dict[str, Any]:
        keys = await self._store.keys("compliance:consent:*")
        total = 0
        consented = 0
        for k in keys:
            raw = await self._store.get(k)
            if raw:
                total += 1
                if raw.get("consented"):
                    consented += 1
        return {"total_customers": total, "consented": consented}


__all__ = ["DEFAULT_DISCLOSURE", "ConsentRecord", "TransparencyManager"]
