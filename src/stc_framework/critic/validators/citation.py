"""Citation-required validator.

A critical class of financial hallucination is a numerical claim with no
source attribution. The :class:`NumericalAccuracyValidator` already
checks that numbers are grounded in the source text — this validator
adds a complementary constraint: if the response contains **any**
numerical claim, it must also contain at least one citation marker
(``[Source: ...]`` / ``[Document: ...]``).

Spec wiring
-----------
Add a rail named ``citation_required`` to ``critic.guardrails.output_rails``.
The default action is ``block`` so audit-relevant responses cannot ship
without an auditor-verifiable source reference.
"""

from __future__ import annotations

import re

from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
    Validator,
)

_NUMBER_RE = re.compile(r"\$[\d,.]+|\d+\.\d+%|\d{1,3}(?:,\d{3})+|\b\d+\b")
_CITATION_RE = re.compile(r"\[(?:Source|Document):\s*[^\]]+\]", re.IGNORECASE)


class CitationRequiredValidator(Validator):
    rail_name = "citation_required"
    severity = "high"

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        response = ctx.response or ""
        if not _NUMBER_RE.search(response):
            # No numbers claimed, nothing to attribute.
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=True,
                severity="low",
                action="pass",
                details="No numerical claims present",
            )
        if _CITATION_RE.search(response):
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=True,
                severity="low",
                action="pass",
                details="Citation present",
            )
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=False,
            severity="high",
            action="block",
            details="Numerical claim without any [Source: ...] citation",
        )
