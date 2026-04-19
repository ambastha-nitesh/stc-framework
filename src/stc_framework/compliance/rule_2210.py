"""FINRA Rule 2210 — communications with the public.

Three responsibilities:

1. **Classify** every communication as ``retail``, ``correspondence``,
   ``institutional``, or ``internal``. Retail triggers the strictest
   rule set.
2. **Detect** pattern-based violations (guarantees, no-risk claims,
   cherry-picking, specific predictions) via the shared pattern
   catalog — so legal updates the YAML, not Python.
3. **Balance** positive vs. risk language — required disclosure
   checking (past-performance references trigger a disclosure lookup).

Outputs a :class:`ReviewResult` per communication. Severe violations
raise :class:`FINRARuleViolation` so the Critic can block the output;
lesser violations return in ``ReviewResult.violations`` for the
principal approval queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from stc_framework.compliance.patterns import (
    PatternCatalog,
    default_finra_catalog,
)
from stc_framework.errors import FINRARuleViolation
from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.metrics import get_metrics


class CommunicationType(str, Enum):
    RETAIL = "retail"
    CORRESPONDENCE = "correspondence"
    INSTITUTIONAL = "institutional"
    INTERNAL = "internal"


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    AUTO_APPROVED = "auto_approved"
    PENDING = "pending"
    RETURNED_FOR_REVISION = "returned_for_revision"
    REJECTED = "rejected"


@dataclass
class ContentViolation:
    violation_type: str
    severity: str  # critical | high | medium | low
    description: str
    offending_text: str
    rule_reference: str = "FINRA 2210"
    suggested_fix: str = ""


# Positive vs risk-indicator keywords for fair-balance scoring.
_POSITIVE_INDICATORS = (
    "opportunity",
    "profit",
    "return",
    "gain",
    "growth",
    "benefit",
    "advantage",
    "outperform",
)
_RISK_INDICATORS = (
    "risk",
    "may lose",
    "loss",
    "not guaranteed",
    "past performance",
    "volatility",
    "fluctuate",
    "downturn",
)


@dataclass
class ReviewResult:
    communication_id: str
    communication_type: CommunicationType
    violations: list[ContentViolation] = field(default_factory=list)
    disclosure_check: dict[str, bool] = field(default_factory=dict)
    fair_balance_score: float = 1.0
    verdict: ReviewDecision = ReviewDecision.AUTO_APPROVED
    requires_principal: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def critical_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "critical")


def _fair_balance(content: str) -> float:
    """Return a 0..1 score where 1 = perfectly balanced.

    ``min(pos, risk) / max(pos, risk)`` per the experimental formula —
    if either side is zero, score is 0. If both are equal, score is 1.
    """
    lowered = content.lower()
    pos = sum(1 for p in _POSITIVE_INDICATORS if p in lowered)
    risk = sum(1 for r in _RISK_INDICATORS if r in lowered)
    if pos == 0 and risk == 0:
        return 1.0  # Pure-fact content; no balance concern.
    if pos == 0 or risk == 0:
        return 0.0
    return min(pos, risk) / max(pos, risk)


class ContentAnalyzer:
    """Core pattern-matching + fair-balance engine.

    Pure function of (content, type); no IO. The engine reads patterns
    from an injected :class:`PatternCatalog` so alternative catalogs
    (state-specific, language-specific) can replace the default.
    """

    def __init__(self, catalog: PatternCatalog | None = None) -> None:
        self._catalog = catalog or default_finra_catalog()

    def analyze(
        self,
        *,
        content: str,
        communication_type: CommunicationType = CommunicationType.RETAIL,
        communication_id: str = "",
        required_disclosures: list[str] | None = None,
    ) -> ReviewResult:
        result = ReviewResult(
            communication_id=communication_id or "unspecified",
            communication_type=communication_type,
        )
        for pattern in self._catalog.scan(content):
            match = pattern.regex.search(content)
            result.violations.append(
                ContentViolation(
                    violation_type=pattern.name,
                    severity=pattern.severity,
                    description=pattern.description,
                    offending_text=match.group(0)[:120] if match else "",
                )
            )

        result.fair_balance_score = _fair_balance(content)
        if result.fair_balance_score < 0.5 and communication_type is CommunicationType.RETAIL:
            result.violations.append(
                ContentViolation(
                    violation_type="fair_balance_failure",
                    severity="high",
                    description="Retail communication lacks sufficient risk balance relative to positive language",
                    offending_text="(structural)",
                    suggested_fix="Add explicit risk disclosure language",
                )
            )

        disclosures = required_disclosures or []
        for d in disclosures:
            result.disclosure_check[d] = d.lower() in content.lower()
        missing = [d for d, present in result.disclosure_check.items() if not present]
        if missing:
            result.violations.append(
                ContentViolation(
                    violation_type="missing_disclosure",
                    severity="high",
                    description=f"Required disclosures missing: {', '.join(missing)}",
                    offending_text="(structural)",
                )
            )

        # Decide the verdict.
        if result.critical_count > 0:
            result.verdict = ReviewDecision.REJECTED
            result.requires_principal = True
        elif any(v.severity == "high" for v in result.violations):
            result.verdict = ReviewDecision.PENDING
            result.requires_principal = communication_type is CommunicationType.RETAIL
        elif result.violations:
            result.verdict = ReviewDecision.APPROVED
            result.requires_principal = False
        else:
            result.verdict = ReviewDecision.AUTO_APPROVED
        return result


_KEY_QUEUE = "compliance:rule_2210:approval_queue:{queue_id}"


class PrincipalApprovalQueue:
    """Awaiting-approval queue for retail communications.

    Principals (registered supervisors) review and approve or reject
    items. Decisions are audited; each item carries enough context for
    a human reviewer to reconstruct the original communication.
    """

    def __init__(self, store: KeyValueStore, *, audit: AuditLogger | None = None) -> None:
        self._store = store
        self._audit = audit

    async def submit(self, item_id: str, review: ReviewResult, *, content: str) -> None:
        await self._store.set(
            _KEY_QUEUE.format(queue_id=item_id),
            {
                "item_id": item_id,
                "content": content,
                "review": _serialize_review(review),
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
            },
        )
        if self._audit:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.PRINCIPAL_APPROVAL_SUBMITTED.value,
                    persona="compliance",
                    extra={"item_id": item_id, "rule": "finra_2210"},
                )
            )

    async def approve(self, item_id: str, *, actor: str, notes: str = "") -> None:
        await self._resolve(item_id, status="approved", actor=actor, notes=notes)
        if self._audit:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.PRINCIPAL_APPROVED.value,
                    persona="compliance",
                    extra={"item_id": item_id, "actor": actor, "notes": notes},
                )
            )

    async def reject(self, item_id: str, *, actor: str, reason: str) -> None:
        await self._resolve(item_id, status="rejected", actor=actor, notes=reason)
        if self._audit:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.PRINCIPAL_REJECTED.value,
                    persona="compliance",
                    extra={"item_id": item_id, "actor": actor, "reason": reason},
                )
            )

    async def pending(self) -> list[dict[str, Any]]:
        keys = await self._store.keys("compliance:rule_2210:approval_queue:*")
        results: list[dict[str, Any]] = []
        for k in keys:
            raw = await self._store.get(k)
            if isinstance(raw, dict) and raw.get("status") == "pending":
                results.append(raw)
        return results

    async def _resolve(self, item_id: str, *, status: str, actor: str, notes: str) -> None:
        raw = await self._store.get(_KEY_QUEUE.format(queue_id=item_id))
        if not raw:
            raise KeyError(f"approval item not found: {item_id!r}")
        raw["status"] = status
        raw["resolved_by"] = actor
        raw["notes"] = notes
        raw["resolved_at"] = datetime.now(timezone.utc).isoformat()
        await self._store.set(_KEY_QUEUE.format(queue_id=item_id), raw)


class Rule2210Engine:
    """Top-level entry point that wires ContentAnalyzer + queue + audit + metrics."""

    def __init__(
        self,
        *,
        store: KeyValueStore,
        analyzer: ContentAnalyzer | None = None,
        audit: AuditLogger | None = None,
        enforce_critical: bool = True,
    ) -> None:
        self._analyzer = analyzer or ContentAnalyzer()
        self._queue = PrincipalApprovalQueue(store=store, audit=audit)
        self._audit = audit
        self._enforce = enforce_critical

    async def review(
        self,
        *,
        content: str,
        communication_type: CommunicationType = CommunicationType.RETAIL,
        communication_id: str = "",
        required_disclosures: list[str] | None = None,
    ) -> ReviewResult:
        result = self._analyzer.analyze(
            content=content,
            communication_type=communication_type,
            communication_id=communication_id,
            required_disclosures=required_disclosures,
        )
        self._emit_metrics(result)
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=(
                        AuditEvent.COMPLIANCE_VIOLATION.value
                        if result.violations
                        else AuditEvent.COMPLIANCE_CHECK_EVALUATED.value
                    ),
                    persona="compliance",
                    extra={
                        "rule": "finra_2210",
                        "communication_id": result.communication_id,
                        "verdict": result.verdict.value,
                        "violation_count": len(result.violations),
                        "fair_balance_score": round(result.fair_balance_score, 3),
                    },
                )
            )
        if result.requires_principal:
            await self._queue.submit(result.communication_id, result, content=content)
        if self._enforce and result.critical_count > 0:
            raise FINRARuleViolation(
                message=f"FINRA Rule 2210 critical violation ({result.critical_count})",
                rule="finra_2210",
            )
        return result

    @property
    def approval_queue(self) -> PrincipalApprovalQueue:
        return self._queue

    def _emit_metrics(self, result: ReviewResult) -> None:
        metrics = get_metrics()
        try:
            metrics.compliance_checks_total.labels(rule="finra_2210", outcome=result.verdict.value).inc()
            for v in result.violations:
                metrics.compliance_violations_total.labels(rule="finra_2210", severity=v.severity).inc()
        except Exception:
            pass


def _serialize_review(result: ReviewResult) -> dict[str, Any]:
    return {
        "communication_id": result.communication_id,
        "communication_type": result.communication_type.value,
        "verdict": result.verdict.value,
        "violations": [
            {
                "type": v.violation_type,
                "severity": v.severity,
                "description": v.description,
                "offending_text": v.offending_text,
            }
            for v in result.violations
        ],
        "fair_balance_score": result.fair_balance_score,
        "requires_principal": result.requires_principal,
        "disclosure_check": dict(result.disclosure_check),
        "timestamp": result.timestamp,
    }


__all__ = [
    "CommunicationType",
    "ContentAnalyzer",
    "ContentViolation",
    "PrincipalApprovalQueue",
    "ReviewDecision",
    "ReviewResult",
    "Rule2210Engine",
]
