"""PII-in-output validator (reuses the Sentinel redactor)."""

from __future__ import annotations

from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
    Validator,
)
from stc_framework.sentinel.redaction import PIIRedactor

_HIGH_RISK = {"CREDIT_CARD", "US_SSN", "US_BANK_NUMBER"}


class PIIOutputValidator(Validator):
    rail_name = "pii_output_scan"
    severity = "critical"

    def __init__(self, redactor: PIIRedactor) -> None:
        self._redactor = redactor

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        try:
            result = self._redactor.redact(ctx.response)
        except Exception:
            # Block was triggered; treat as failure.
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=False,
                severity="critical",
                action="block",
                details="Response contains blocked PII entity",
            )

        high_risk = [k for k in result.entity_counts if k in _HIGH_RISK]
        any_pii = bool(result.entity_counts)

        if high_risk:
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=False,
                severity="critical",
                action="block",
                details=f"{len(high_risk)} high-risk PII entities in output",
                evidence={"entities": list(result.entity_counts)},
            )
        if any_pii:
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=True,
                severity="low",
                action="redact",
                details="Non-critical PII found; caller may redact",
                evidence={"entities": list(result.entity_counts)},
            )
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=True,
            severity="low",
            action="pass",
            details="No PII detected in output",
        )
