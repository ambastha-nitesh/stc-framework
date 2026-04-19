"""Critic validator bridging sovereignty / model-origin checks.

Enforces the operator-declared model-origin allow-list on every
response. The bridge reads the model id from
``ctx.metadata["model_id"]`` (populated by the Stalwart agent when it
records the LLM that produced the response) and asks
:class:`ModelOriginPolicy` whether the origin is allowed for the
current ``data_tier``.

Use cases:

* Enforcing "restricted-tier data may only leave via trusted-origin
  models" at the output rail, even if an upstream routing bug let a
  restricted-tier request reach a disallowed model.
* Adding a belt-and-braces check on top of the Sentinel routing guard.
"""

from __future__ import annotations

from dataclasses import dataclass

from stc_framework.compliance.sovereignty.model_origin import ModelOriginPolicy
from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
)


@dataclass
class SovereigntyRailBridge:
    """Rejects responses produced by a model outside the origin allow-list."""

    policy: ModelOriginPolicy
    rail_name: str = "compliance_model_origin"
    severity: str = "critical"

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        model_id = str(ctx.metadata.get("model_id", ""))
        if not model_id:
            # Nothing to check — the Stalwart did not annotate the response.
            # Deliberately returns ``passed=True`` so an absent annotation
            # does not hard-block legitimate traffic; production should
            # instrument the pipeline so this branch never runs.
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=True,
                severity="low",
                action="pass",
                details="model_id missing from context metadata; skipping origin check",
                evidence={"model_id": None},
            )
        decision = self.policy.evaluate(model_id)
        if decision["allowed"]:
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=True,
                severity="low",
                action="pass",
                details=decision["reason"],
                evidence={
                    "model_id": model_id,
                    "origin_risk": decision.get("origin_risk"),
                    "headquarters_country": decision.get("headquarters_country"),
                },
            )
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=False,
            severity=self.severity,
            action="block",
            details=f"model {model_id!r} origin disallowed: {decision['reason']}",
            evidence={
                "model_id": model_id,
                "origin_risk": decision.get("origin_risk"),
                "headquarters_country": decision.get("headquarters_country"),
            },
        )


__all__ = ["SovereigntyRailBridge"]
