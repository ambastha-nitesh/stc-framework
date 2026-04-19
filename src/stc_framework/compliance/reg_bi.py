"""Reg BI — Regulation Best Interest suitability checkpoint.

Reg BI (17 CFR 240.15l-1) requires that broker-dealers recommending
securities transactions act in the retail customer's best interest.
This checkpoint evaluates AI-generated advisory content against a
customer profile and flags unsuitable material.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from stc_framework.errors import RegBIUnsuitable
from stc_framework.governance.events import AuditEvent
from stc_framework.observability.audit import AuditLogger, AuditRecord


class SuitabilityResult(str, Enum):
    SUITABLE = "suitable"
    UNSUITABLE = "unsuitable"
    NEEDS_REVIEW = "needs_review"
    NOT_APPLICABLE = "not_applicable"


# Risk-indicator keyword sets — product-class proxies for a full
# suitability engine. Real implementations would consult a structured
# product database; these keywords are sufficient for detection +
# manual-review escalation.
_HIGH_RISK_INDICATORS = (
    "derivatives",
    "options",
    "leveraged etf",
    "futures",
    "margin account",
    "penny stock",
    "private placement",
    "crypto",
)
_LOW_RISK_INDICATORS = (
    "treasury bond",
    "money market",
    "certificate of deposit",
    "municipal bond",
    "index fund",
)


@dataclass
class CustomerProfile:
    customer_id: str
    risk_tolerance: str = "moderate"  # conservative | moderate | aggressive
    investment_objectives: list[str] = field(default_factory=list)
    time_horizon: str = "long"  # short | medium | long
    age_bracket: str = "unknown"
    accredited: bool = False


@dataclass
class SuitabilityCheckResult:
    customer_id: str
    result: SuitabilityResult
    reasons: list[str] = field(default_factory=list)
    risk_level_detected: str = "moderate"
    needs_disclosure: bool = False


class RegBICheckpoint:
    """Evaluate content against a customer's suitability profile."""

    def __init__(self, *, audit: AuditLogger | None = None, enforce: bool = False) -> None:
        self._audit = audit
        self._enforce = enforce

    def _detect_risk_level(self, content: str) -> str:
        lowered = content.lower()
        if any(ind in lowered for ind in _HIGH_RISK_INDICATORS):
            return "high"
        if any(ind in lowered for ind in _LOW_RISK_INDICATORS):
            return "low"
        return "moderate"

    async def check(
        self,
        *,
        content: str,
        customer: CustomerProfile,
        context: dict[str, Any] | None = None,
    ) -> SuitabilityCheckResult:
        risk_level = self._detect_risk_level(content)
        reasons: list[str] = []
        result = SuitabilityResult.SUITABLE

        if risk_level == "high" and customer.risk_tolerance == "conservative":
            reasons.append("high-risk product recommended to conservative-risk-tolerance customer")
            result = SuitabilityResult.UNSUITABLE
        elif risk_level == "high" and not customer.accredited and customer.age_bracket == "senior":
            reasons.append("high-risk product recommended to non-accredited senior customer")
            result = SuitabilityResult.NEEDS_REVIEW
        elif risk_level == "low" and customer.risk_tolerance == "aggressive":
            reasons.append("low-risk product may not meet aggressive investor objectives")
            result = SuitabilityResult.NEEDS_REVIEW

        check = SuitabilityCheckResult(
            customer_id=customer.customer_id,
            result=result,
            reasons=reasons,
            risk_level_detected=risk_level,
            needs_disclosure=result is not SuitabilityResult.SUITABLE,
        )
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.COMPLIANCE_CHECK_EVALUATED.value,
                    persona="compliance",
                    extra={
                        "rule": "reg_bi",
                        "customer_id": customer.customer_id,
                        "result": result.value,
                        "risk_level": risk_level,
                    },
                )
            )
        if self._enforce and result is SuitabilityResult.UNSUITABLE:
            raise RegBIUnsuitable(
                message=f"Reg BI: unsuitable for customer {customer.customer_id!r}",
                rule="reg_bi",
            )
        return check


__all__ = ["CustomerProfile", "RegBICheckpoint", "SuitabilityCheckResult", "SuitabilityResult"]
