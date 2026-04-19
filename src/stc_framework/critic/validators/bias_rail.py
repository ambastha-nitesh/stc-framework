"""Critic validator bridging :class:`BiasFairnessMonitor` into the rails.

The monitor tracks per-demographic-group response quality. When the
EEOC 4/5ths ratio crosses below 0.80 for any group, the bridge emits a
high-severity guardrail result. The monitor needs at least two
populated groups to evaluate; until that condition holds the bridge is
a no-op.

Callers feed quality signals into the monitor from elsewhere (a
``QueryResult`` post-processor or a separate evaluation pipeline); the
bridge only reads the monitor — it does not decide what a "quality"
score means.
"""

from __future__ import annotations

from dataclasses import dataclass

from stc_framework.compliance.bias_fairness import (
    ADVERSE_IMPACT_RATIO,
    BiasFairnessMonitor,
)
from stc_framework.critic.validators.base import (
    GuardrailResult,
    ValidationContext,
)


@dataclass
class BiasRailBridge:
    """Output-rail validator that queries :class:`BiasFairnessMonitor`.

    The bridge reads ``ctx.metadata["reference_group"]`` (optional)
    to pick the reference demographic; the monitor picks the
    highest-mean group automatically when absent.
    """

    monitor: BiasFairnessMonitor
    rail_name: str = "compliance_bias_fairness"
    severity: str = "high"

    async def avalidate(self, ctx: ValidationContext) -> GuardrailResult:
        reference = ctx.metadata.get("reference_group")
        report = await self.monitor.evaluate_fairness(reference_group=reference)
        adverse = [f for f in report.findings if f.adverse_impact]
        if not adverse:
            return GuardrailResult(
                rail_name=self.rail_name,
                passed=True,
                severity="low",
                action="pass",
                details="no adverse impact detected",
                evidence={
                    "reference_group": report.reference_group,
                    "group_means": report.per_group,
                },
            )
        return GuardrailResult(
            rail_name=self.rail_name,
            passed=False,
            severity=self.severity,
            action="warn",  # bias warrants human review, not hard block
            details=(
                f"adverse impact detected for {len(adverse)} group(s) "
                f"vs reference {report.reference_group!r} "
                f"(4/5ths threshold {ADVERSE_IMPACT_RATIO})"
            ),
            evidence={
                "reference_group": report.reference_group,
                "adverse_groups": [{"group": f.group, "ratio": f.ratio, "rate": f.group_rate} for f in adverse],
            },
        )


__all__ = ["BiasRailBridge"]
