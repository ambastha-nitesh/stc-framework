"""Typed error taxonomy for the STC Framework.

All framework errors inherit from :class:`STCError` and carry enough
structured context (trace id, persona, downstream service) for callers to
map them to HTTP status codes, metrics labels, or retry decisions without
parsing messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class STCError(Exception):
    """Base class for all STC Framework errors.

    Parameters
    ----------
    message:
        Human-readable description.
    trace_id:
        The correlation id of the request; ``None`` if raised outside a
        traced context.
    persona:
        Which STC persona raised the error (``"stalwart"``, ``"trainer"``,
        ``"critic"``, ``"sentinel"``) — mostly for metrics labelling.
    downstream:
        Name of the external dependency involved, e.g. ``"litellm"``,
        ``"qdrant"``. Used to key circuit breakers and metrics.
    retryable:
        Hint to callers whether retrying makes sense.
    context:
        Arbitrary extra fields for logging.

    """

    message: str = ""
    trace_id: str | None = None
    persona: str | None = None
    downstream: str | None = None
    retryable: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        parts = [self.message or self.__class__.__name__]
        if self.downstream:
            parts.append(f"downstream={self.downstream}")
        if self.trace_id:
            parts.append(f"trace={self.trace_id}")
        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Configuration / spec errors
# ---------------------------------------------------------------------------


@dataclass
class ConfigError(STCError):
    """Invalid or missing configuration discovered at startup."""


@dataclass
class SpecValidationError(ConfigError):
    """The declarative spec failed pydantic validation.

    ``context['errors']`` contains the list of raw pydantic error dicts so
    tooling can render them structurally.
    """


# ---------------------------------------------------------------------------
# Data sovereignty / sentinel
# ---------------------------------------------------------------------------


@dataclass
class DataSovereigntyViolation(STCError):
    """An operation would cross a forbidden data-sovereignty boundary."""


@dataclass
class TierRoutingError(DataSovereigntyViolation):
    """No model endpoint is available for the requested data tier."""


@dataclass
class TokenizationError(STCError):
    """Surrogate tokenization or detokenization failed."""


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@dataclass
class LLMError(STCError):
    """Generic LLM call failure."""

    retryable: bool = True


@dataclass
class LLMTimeout(LLMError):
    """LLM call exceeded the configured timeout."""


@dataclass
class LLMRateLimited(LLMError):
    """LLM provider returned a rate-limit response."""


@dataclass
class LLMQuotaExceeded(LLMError):
    """LLM provider returned a quota/budget exhaustion response."""

    retryable: bool = False


@dataclass
class LLMUnavailable(LLMError):
    """LLM provider is unreachable or returned 5xx."""


@dataclass
class LLMContentFiltered(LLMError):
    """Provider refused to respond due to upstream content filtering."""

    retryable: bool = False


# ---------------------------------------------------------------------------
# Vector store / embeddings
# ---------------------------------------------------------------------------


@dataclass
class VectorStoreError(STCError):
    """Generic vector store failure."""

    retryable: bool = True


@dataclass
class VectorStoreUnavailable(VectorStoreError):
    """Vector store endpoint is unreachable."""


@dataclass
class CollectionMissing(VectorStoreError):
    """Requested collection does not exist."""

    retryable: bool = False


@dataclass
class EmbeddingError(STCError):
    """Embedding computation failed."""

    retryable: bool = True


# ---------------------------------------------------------------------------
# Guardrails / governance
# ---------------------------------------------------------------------------


@dataclass
class GuardrailError(STCError):
    """Guardrail evaluation itself failed (not a policy failure)."""

    retryable: bool = True


@dataclass
class GuardrailBlocked(STCError):
    """A guardrail intentionally blocked the response."""

    retryable: bool = False


@dataclass
class GuardrailTimeout(GuardrailError):
    """Guardrail evaluation exceeded its timeout."""


@dataclass
class EscalationActive(STCError):
    """The Critic has escalated; further traffic is paused or degraded."""

    level: str = "degraded"
    retryable: bool = False


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


@dataclass
class CircuitBreakerOpen(STCError):
    """Downstream circuit breaker is open."""

    retryable: bool = False


@dataclass
class RetryExhausted(STCError):
    """Retries were exhausted without success."""

    last_error: str | None = None
    retryable: bool = False


@dataclass
class BulkheadFull(STCError):
    """Concurrency limit for a downstream was reached."""

    retryable: bool = True


@dataclass
class PromptRegistryError(STCError):
    """Prompt registry operation failed (missing version, write failure...)."""


# ---------------------------------------------------------------------------
# Compliance (v0.3.0)
# ---------------------------------------------------------------------------


@dataclass
class ComplianceViolation(STCError):
    """A compliance rule evaluation blocked the operation."""

    rule: str = ""
    retryable: bool = False


@dataclass
class FINRARuleViolation(ComplianceViolation):
    """FINRA Rule 2210 or related communication-rule violation."""


@dataclass
class RegBIUnsuitable(ComplianceViolation):
    """Reg BI suitability check determined content is unsuitable for the customer."""


@dataclass
class DisclosureMissing(ComplianceViolation):
    """Required regulatory disclosure is absent from the communication."""


@dataclass
class LegalHoldActive(ComplianceViolation):
    """An active legal hold prohibits the destruction or modification operation."""

    hold_id: str = ""


# ---------------------------------------------------------------------------
# Risk (v0.3.0)
# ---------------------------------------------------------------------------


@dataclass
class RiskAssessmentError(STCError):
    """Generic failure during a risk evaluation."""


@dataclass
class KRIRedVeto(RiskAssessmentError):
    """A Key Risk Indicator is in RED and vetoes the proposed action."""

    kri_id: str = ""
    retryable: bool = False


@dataclass
class RiskAppetiteBreach(RiskAssessmentError):
    """Proposed action would breach the declared risk appetite."""

    retryable: bool = False


@dataclass
class RiskOptimizerVeto(RiskAssessmentError):
    """Risk-adjusted optimizer rejected every candidate decision."""

    retryable: bool = False


# ---------------------------------------------------------------------------
# Threats (v0.3.0)
# ---------------------------------------------------------------------------


@dataclass
class ThreatDetected(STCError):
    """A threat-detection subsystem classified the request as hostile."""

    threat_type: str = ""
    severity: str = "high"
    retryable: bool = False


@dataclass
class DDoSDetected(ThreatDetected):
    """Edge rate-limiter or cost-exhaustion detector tripped."""


@dataclass
class HoneyTokenTriggered(ThreatDetected):
    """A honey token or canary was accessed — high-confidence insider abuse."""


@dataclass
class BehavioralAnomalyDetected(ThreatDetected):
    """UEBA-style behavioural analyser flagged the session."""


# ---------------------------------------------------------------------------
# Orchestration (v0.3.0)
# ---------------------------------------------------------------------------


@dataclass
class OrchestrationError(STCError):
    """Generic failure in the multi-Stalwart workflow engine."""


@dataclass
class WorkflowBudgetExhausted(OrchestrationError):
    """Workflow-level cost or token budget was consumed before completion."""

    retryable: bool = False


@dataclass
class StalwartDispatchFailed(OrchestrationError):
    """No registered Stalwart could satisfy a required capability tag."""

    capability: str = ""
    retryable: bool = False


@dataclass
class WorkflowCriticRejected(OrchestrationError):
    """The Workflow Critic failed the aggregated multi-task output."""

    retryable: bool = False


# ---------------------------------------------------------------------------
# Session state (v0.3.0)
# ---------------------------------------------------------------------------


@dataclass
class SessionStateError(STCError):
    """Generic session-state failure."""


@dataclass
class SessionExpired(SessionStateError):
    """Session TTL elapsed; caller must create a new session."""

    retryable: bool = False


@dataclass
class SessionBackendUnavailable(SessionStateError):
    """The pluggable session-state backend is unreachable."""

    retryable: bool = True


# ---------------------------------------------------------------------------
# Convenience: HTTP status code mapping used by the Flask service layer.
# ---------------------------------------------------------------------------


def http_status_for(error: STCError) -> int:
    """Map an :class:`STCError` to a sensible HTTP status code."""
    mapping: dict[type[STCError], int] = {
        ConfigError: 500,
        SpecValidationError: 500,
        DataSovereigntyViolation: 403,
        TierRoutingError: 403,
        TokenizationError: 500,
        LLMTimeout: 504,
        LLMRateLimited: 429,
        LLMQuotaExceeded: 402,
        LLMUnavailable: 503,
        LLMContentFiltered: 422,
        LLMError: 502,
        VectorStoreUnavailable: 503,
        CollectionMissing: 404,
        VectorStoreError: 502,
        EmbeddingError: 502,
        GuardrailBlocked: 422,
        GuardrailTimeout: 504,
        GuardrailError: 502,
        EscalationActive: 503,
        CircuitBreakerOpen: 503,
        RetryExhausted: 502,
        BulkheadFull: 503,
        PromptRegistryError: 500,
        # v0.3.0 compliance
        FINRARuleViolation: 422,
        RegBIUnsuitable: 422,
        DisclosureMissing: 422,
        LegalHoldActive: 423,  # 423 Locked
        ComplianceViolation: 422,
        # v0.3.0 risk
        KRIRedVeto: 503,
        RiskAppetiteBreach: 403,
        RiskOptimizerVeto: 503,
        RiskAssessmentError: 500,
        # v0.3.0 threats
        DDoSDetected: 429,
        HoneyTokenTriggered: 403,
        BehavioralAnomalyDetected: 403,
        ThreatDetected: 403,
        # v0.3.0 orchestration
        WorkflowBudgetExhausted: 402,
        StalwartDispatchFailed: 503,
        WorkflowCriticRejected: 502,
        OrchestrationError: 500,
        # v0.3.0 session
        SessionExpired: 440,  # 440 Login Time-out (de-facto session expired)
        SessionBackendUnavailable: 503,
        SessionStateError: 500,
    }
    for cls in type(error).__mro__:
        if cls in mapping:
            return mapping[cls]
    return 500
