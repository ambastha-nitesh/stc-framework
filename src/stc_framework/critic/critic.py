"""Critic orchestrator.

Wires validators, rail runner, and escalation manager into a single API:

- :meth:`Critic.aevaluate_input` runs the spec's ``input_rails`` against the
  user query before Stalwart executes.
- :meth:`Critic.aevaluate_output` runs ``output_rails`` against the
  generated response and returns a :class:`GovernanceVerdict`.
- :meth:`Critic.format_trainer_feedback` formats that verdict for the
  Trainer to consume.
"""

from __future__ import annotations

from typing import Any

from stc_framework.config.logging import get_logger
from stc_framework.critic.escalation import EscalationManager
from stc_framework.critic.rails import RailRunner
from stc_framework.critic.validators import (
    CitationRequiredValidator,
    GovernanceVerdict,
    GuardrailResult,
    HallucinationValidator,
    NumericalAccuracyValidator,
    PIIOutputValidator,
    PromptInjectionValidator,
    ScopeValidator,
    ToxicityValidator,
    ValidationContext,
    Validator,
)
from stc_framework.observability.metrics import get_metrics
from stc_framework.observability.tracing import get_tracer
from stc_framework.sentinel.redaction import PIIRedactor
from stc_framework.spec.models import STCSpec

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class Critic:
    """Zero-trust governance orchestrator."""

    def __init__(
        self,
        spec: STCSpec,
        *,
        redactor: PIIRedactor,
        embeddings: Any | None = None,
        external_guardrails: Any | None = None,
        rail_timeout_sec: float = 5.0,
        rail_bulkhead: int = 128,
    ) -> None:
        self._spec = spec

        # Build default validators using spec configuration.
        numerical_rail = spec.rail_by_name("numerical_accuracy")
        tolerance = numerical_rail.tolerance_percent if numerical_rail else 1.0

        hallucination_rail = spec.rail_by_name("hallucination_detection")
        hallucination_threshold = hallucination_rail.threshold if hallucination_rail else 0.8

        investment_rail = spec.rail_by_name("investment_advice_detection")
        scope_rail = spec.rail_by_name("scope_check")

        prohibited = list(investment_rail.prohibited_topics) if investment_rail else []
        allowed = list(scope_rail.allowed_topics) if scope_rail else []

        validators: dict[str, Validator] = {
            "numerical_accuracy": NumericalAccuracyValidator(tolerance_percent=tolerance or 1.0),
            "hallucination_detection": HallucinationValidator(
                threshold=hallucination_threshold or 0.8, embeddings=embeddings
            ),
            "investment_advice_detection": ScopeValidator(prohibited_topics=prohibited, action_on_prohibited="block"),
            "scope_check": ScopeValidator(allowed_topics=allowed),
            "pii_output_scan": PIIOutputValidator(redactor=redactor),
            "prompt_injection_detection": PromptInjectionValidator(),
            "pii_input_scan": PIIOutputValidator(redactor=redactor),
            "toxicity_check": ToxicityValidator(external=external_guardrails),
            # Defence-in-depth: also look for injection artefacts the
            # model may have echoed back in its response. A poisoned
            # document can force the model to emit instructions that
            # the *next* system in a downstream agent chain would
            # execute — blocking at our boundary protects the chain.
            "output_injection_scan": PromptInjectionValidator(),
            # Numerical claims without citations are the most common
            # class of financial hallucination. This validator refuses
            # to ship such responses unless the spec explicitly
            # disables it (e.g. for a non-financial domain where
            # uncited numbers are acceptable).
            "citation_required": CitationRequiredValidator(),
        }
        # Registration is intentionally by dict-literal keyed on the
        # exact string the spec uses. A typo here vs. a typo in the
        # spec are both silently ignorable — pytest's
        # test_privacy.py::TestAuditCoverage catches the "wired but
        # never fires" case; a mismatched key surfaces as the rail
        # simply not being invoked.
        self._rail_runner = RailRunner(validators, timeout_sec=rail_timeout_sec, bulkhead_limit=rail_bulkhead)
        self._escalation = EscalationManager(spec.critic.escalation)

    def register_validator(self, validator: Validator) -> None:
        """Plug in a custom validator (used by reference implementations)."""
        self._rail_runner.register(validator)

    @property
    def escalation(self) -> EscalationManager:
        return self._escalation

    # ------------------------------------------------------------------
    # Input rails
    # ------------------------------------------------------------------
    async def aevaluate_input(self, query: str, *, trace_id: str = "") -> GovernanceVerdict:
        ctx = ValidationContext(query=query, response="", trace_id=trace_id)
        with _tracer.start_as_current_span("critic.input_rails"):
            results = await self._rail_runner.run(self._spec.input_rails(), ctx)
        return self._aggregate(trace_id, results)

    # ------------------------------------------------------------------
    # Output rails
    # ------------------------------------------------------------------
    async def aevaluate_output(self, data: dict[str, Any]) -> GovernanceVerdict:
        ctx = ValidationContext(
            query=data.get("query", ""),
            response=data.get("response", ""),
            context=data.get("context", ""),
            source_chunks=list(data.get("retrieved_chunks", []) or []),
            trace_id=data.get("trace_id", ""),
            data_tier=data.get("data_tier", "public"),
            metadata=dict(data.get("metadata", {}) or {}),
        )
        with _tracer.start_as_current_span("critic.output_rails"):
            results = await self._rail_runner.run(self._spec.output_rails(), ctx)

        verdict = self._aggregate(ctx.trace_id, results)
        self._escalation.record_result(verdict)
        if self._escalation.current_level is not None:
            verdict.escalation_level = self._escalation.current_level
            verdict.action = "escalate"
        return verdict

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _aggregate(self, trace_id: str, results: list[GuardrailResult]) -> GovernanceVerdict:
        metrics = get_metrics()
        for r in results:
            if not r.passed:
                metrics.guardrail_failures_total.labels(rail=r.rail_name, severity=r.severity).inc()

        critical_fails = [r for r in results if not r.passed and r.severity == "critical"]
        any_fails = [r for r in results if not r.passed]

        if critical_fails:
            action = "block"
            passed = False
        elif any_fails:
            action = "warn"
            passed = True
        else:
            action = "pass"
            passed = True

        return GovernanceVerdict(
            trace_id=trace_id,
            passed=passed,
            results=results,
            action=action,
        )

    @staticmethod
    def format_trainer_feedback(verdict: GovernanceVerdict) -> dict[str, Any]:
        return {
            "trace_id": verdict.trace_id,
            "governance_passed": verdict.passed,
            "action_taken": verdict.action,
            "failures": [
                {
                    "rail": r.rail_name,
                    "severity": r.severity,
                    "details": r.details,
                    "evidence": r.evidence,
                }
                for r in verdict.results
                if not r.passed
            ],
            "escalation_level": verdict.escalation_level,
            "timestamp": verdict.timestamp,
        }
