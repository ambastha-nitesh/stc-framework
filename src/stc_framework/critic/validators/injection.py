"""Prompt-injection detection for input rails.

Thin wrapper around :mod:`stc_framework.security.injection` so the Critic
and any external consumer share the exact same rule set. Every rule match
is surfaced in the ``evidence`` payload so auditors can tell *why* a
request was blocked.
"""

from __future__ import annotations

from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
    Validator,
)
from stc_framework.security.injection import (
    detect_injection,
    redact_injection_snippets,
)


class PromptInjectionValidator(Validator):
    rail_name = "prompt_injection_detection"
    severity = "critical"

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        text = ctx.query or ctx.response  # input or output rail
        matches = detect_injection(text)
        if matches:
            rule_names = ", ".join(sorted({m.rule for m in matches}))
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=False,
                severity="critical",
                action="block",
                details=f"Injection patterns detected: {rule_names}",
                evidence={"matches": redact_injection_snippets(matches)},
            )
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=True,
            severity="low",
            action="pass",
            details="No injection patterns detected",
        )
