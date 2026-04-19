"""Critic validator bridging :class:`Rule2210Engine` into the rail pipeline.

Wiring a FINRA Rule 2210 check into the declarative spec becomes:

    critic:
      guardrails:
        output_rails:
          - name: compliance_finra_2210
            severity: critical
            action: block

Callers construct the bridge once at system boot and register it with
the Critic:

    engine = Rule2210Engine(store=InMemoryStore())
    critic.register_validator(ComplianceRailBridge(engine))

Every output response is then reviewed; critical violations surface as
blocked guardrail results instead of raised exceptions, so the Critic's
aggregation logic (not ad-hoc try/except branches) picks the final
action.
"""

from __future__ import annotations

from dataclasses import dataclass

from stc_framework.compliance.rule_2210 import (
    CommunicationType,
    ReviewDecision,
    Rule2210Engine,
)
from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
)


@dataclass
class ComplianceRailBridge:
    """Output-rail validator that delegates to :class:`Rule2210Engine`.

    The bridge operates in **non-enforcing** mode — the engine itself
    is constructed with ``enforce_critical=False`` by the caller so
    violations surface as guardrail results rather than raised
    exceptions. That lets the Critic's aggregation logic decide the
    final action (and lets lower-severity findings flow to the
    principal-approval queue without aborting the request).
    """

    engine: Rule2210Engine
    rail_name: str = "compliance_finra_2210"
    severity: str = "critical"

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        comm_type = CommunicationType(ctx.metadata.get("communication_type", CommunicationType.RETAIL.value))
        disclosures = list(ctx.metadata.get("required_disclosures", []))
        review = await self.engine.review(
            content=ctx.response,
            communication_type=comm_type,
            communication_id=ctx.trace_id or "unspecified",
            required_disclosures=disclosures or None,
        )
        passed = review.verdict in (ReviewDecision.APPROVED, ReviewDecision.AUTO_APPROVED)
        if review.critical_count > 0:
            action = "block"
            result_severity = "critical"
        elif review.violations:
            action = "warn"
            result_severity = "high"
        else:
            action = "pass"
            result_severity = "low"
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=passed,
            severity=result_severity,
            action=action,
            details=f"finra_2210 verdict={review.verdict.value}; violations={len(review.violations)}",
            evidence={
                "verdict": review.verdict.value,
                "violation_types": [v.violation_type for v in review.violations],
                "fair_balance_score": review.fair_balance_score,
                "requires_principal": review.requires_principal,
            },
        )


__all__ = ["ComplianceRailBridge"]
