"""Toxicity validator.

If a NeMo-backed external guardrail is supplied, uses that; otherwise a
keyword-heuristic default fires for obvious cases.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
    Validator,
)

if TYPE_CHECKING:
    from stc_framework.adapters.guardrails.base import ExternalGuardrailClient


_TOXIC_PATTERNS = [
    re.compile(r"\bhate\s+(?:you|them|this)\b", re.IGNORECASE),
    re.compile(r"\b(?:idiot|moron|stupid)\b", re.IGNORECASE),
    re.compile(r"\b(?:kill|murder)\s+(?:yourself|them)\b", re.IGNORECASE),
]


class ToxicityValidator(Validator):
    rail_name = "toxicity_check"
    severity = "medium"

    def __init__(
        self,
        *,
        external: ExternalGuardrailClient | None = None,
        threshold: float = 0.7,
    ) -> None:
        self._external = external
        self._threshold = threshold

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        if self._external is not None:
            check = await self._external.check(self.rail_name, ctx.response)
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=check.passed,
                severity=check.severity,
                action="pass" if check.passed else "block",
                details=check.details,
                evidence=check.evidence,
            )

        for pattern in _TOXIC_PATTERNS:
            if pattern.search(ctx.response):
                return GuardrailResult(
                    rail_name=self.rail_name,
                    passed=False,
                    severity="medium",
                    action="block",
                    details="Heuristic toxicity match",
                )
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=True,
            severity="low",
            action="pass",
            details="No toxic content detected",
        )
