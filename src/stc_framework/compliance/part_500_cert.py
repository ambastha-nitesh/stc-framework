"""NYDFS 23 NYCRR Part 500 — annual certification assembler.

Collects evidence across the 17 required program sections (risk
assessment, cybersecurity policy, CISO designation, access privileges,
audit trail, multi-factor authentication, training, incident response,
etc.) and assembles a certification package for the board / NYDFS.

Evidence items are stored through :class:`KeyValueStore`; the assembly
step produces a structured dict suitable for PDF / HTML rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord

# The 17 Part 500 sections — section ids follow the regulation.
PART_500_SECTIONS: tuple[str, ...] = (
    "500.02_cybersecurity_program",
    "500.03_cybersecurity_policy",
    "500.04_ciso_designation",
    "500.05_penetration_testing",
    "500.06_audit_trail",
    "500.07_access_privileges",
    "500.08_application_security",
    "500.09_risk_assessment",
    "500.10_personnel",
    "500.11_third_party",
    "500.12_mfa",
    "500.13_limitations_on_data_retention",
    "500.14_training_and_monitoring",
    "500.15_encryption",
    "500.16_incident_response",
    "500.17_notification",
    "500.19_exemptions",
)


@dataclass
class EvidenceItem:
    section_id: str
    title: str
    description: str = ""
    status: str = "satisfied"  # satisfied | gap | exception
    evidence_url: str = ""
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GapRecord:
    section_id: str
    description: str
    remediation_plan: str = ""
    target_date: str | None = None


_KEY_EVIDENCE = "compliance:part500:evidence:{section_id}:{evidence_id}"
_KEY_GAP = "compliance:part500:gap:{gap_id}"


class Part500CertificationAssembler:
    """Collects evidence + gaps across the 17 Part 500 sections."""

    def __init__(self, store: KeyValueStore, *, audit: AuditLogger | None = None) -> None:
        self._store = store
        self._audit = audit

    async def add_evidence(self, section_id: str, evidence_id: str, item: EvidenceItem) -> None:
        if section_id not in PART_500_SECTIONS:
            raise ValueError(f"unknown Part 500 section: {section_id!r}")
        await self._store.set(
            _KEY_EVIDENCE.format(section_id=section_id, evidence_id=evidence_id),
            {
                "section_id": section_id,
                "evidence_id": evidence_id,
                "title": item.title,
                "description": item.description,
                "status": item.status,
                "evidence_url": item.evidence_url,
                "collected_at": item.collected_at,
                "metadata": dict(item.metadata),
            },
        )
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.COMPLIANCE_CHECK_EVALUATED.value,
                    persona="compliance",
                    extra={
                        "rule": "nydfs_part_500",
                        "action": "evidence_added",
                        "section": section_id,
                        "evidence_id": evidence_id,
                    },
                )
            )

    async def add_gap(self, gap_id: str, gap: GapRecord) -> None:
        await self._store.set(
            _KEY_GAP.format(gap_id=gap_id),
            {
                "gap_id": gap_id,
                "section_id": gap.section_id,
                "description": gap.description,
                "remediation_plan": gap.remediation_plan,
                "target_date": gap.target_date,
            },
        )

    async def assemble(self, certification_year: int) -> dict[str, Any]:
        """Return a structured snapshot of evidence + gaps per section."""
        sections: dict[str, dict[str, Any]] = {s: {"evidence": [], "gaps": []} for s in PART_500_SECTIONS}
        # Evidence
        for k in await self._store.keys("compliance:part500:evidence:*"):
            raw = await self._store.get(k)
            if isinstance(raw, dict) and raw.get("section_id") in sections:
                sections[raw["section_id"]]["evidence"].append(raw)
        # Gaps
        for k in await self._store.keys("compliance:part500:gap:*"):
            raw = await self._store.get(k)
            if isinstance(raw, dict) and raw.get("section_id") in sections:
                sections[raw["section_id"]]["gaps"].append(raw)
        status_counts = {"satisfied": 0, "gap": 0, "exception": 0}
        for s in sections.values():
            for ev in s["evidence"]:
                status_counts[ev.get("status", "satisfied")] = status_counts.get(ev.get("status", "satisfied"), 0) + 1
        return {
            "certification_year": certification_year,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sections": sections,
            "section_count": len(PART_500_SECTIONS),
            "status_counts": status_counts,
            "total_gaps": sum(len(s["gaps"]) for s in sections.values()),
        }


__all__ = [
    "PART_500_SECTIONS",
    "EvidenceItem",
    "GapRecord",
    "Part500CertificationAssembler",
]
