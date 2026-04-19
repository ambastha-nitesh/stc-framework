"""Sentinel gateway: the single choke point for every LLM call.

Responsibilities (in order):

1. Classify the request's data tier.
2. Redact PII per spec.
3. (Optionally) surrogate-tokenize residual sensitive values.
4. Select a model from the Trainer's preferred routing for that tier.
5. Execute with fallback-chain / retry / circuit-breaker / timeout / bulkhead.
6. Audit the boundary crossing.
7. Return a typed response.

The gateway is **async-first**; a sync facade is exposed via
:meth:`SentinelGateway.completion`.
"""

from __future__ import annotations

import asyncio
from threading import RLock
from typing import Any

from stc_framework.adapters.llm.base import ChatMessage, LLMClient, LLMResponse
from stc_framework.config.logging import get_logger
from stc_framework.errors import (
    CircuitBreakerOpen,
    DataSovereigntyViolation,
    LLMError,
    TierRoutingError,
)
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.correlation import current_correlation
from stc_framework.observability.metrics import get_metrics
from stc_framework.observability.tracing import get_tracer
from stc_framework.resilience.bulkhead import Bulkhead
from stc_framework.resilience.circuit import get_circuit
from stc_framework.resilience.fallback import run_with_fallback
from stc_framework.resilience.retry import with_retry
from stc_framework.resilience.timeout import atimeout
from stc_framework.sentinel.classifier import DataClassifier
from stc_framework.sentinel.redaction import PIIRedactor
from stc_framework.sentinel.tokenization import Tokenizer
from stc_framework.spec.models import STCSpec
from stc_framework.spec.routing_guard import is_local_model as _is_local_model

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)


class SentinelGateway:
    """Guards every cross-boundary LLM call."""

    def __init__(
        self,
        spec: STCSpec,
        llm: LLMClient,
        *,
        redactor: PIIRedactor,
        classifier: DataClassifier,
        tokenizer: Tokenizer | None = None,
        audit: AuditLogger | None = None,
        llm_timeout_sec: float = 30.0,
        llm_max_attempts: int = 3,
        llm_bulkhead: int = 64,
        circuit_fail_max: int = 5,
        circuit_reset_sec: float = 30.0,
    ) -> None:
        self._spec = spec
        self._llm = llm
        self._redactor = redactor
        self._classifier = classifier
        self._tokenizer = tokenizer
        self._audit = audit

        self._timeout = llm_timeout_sec
        self._max_attempts = llm_max_attempts
        self._bulkhead = Bulkhead("llm", llm_bulkhead)
        self._circuit_fail_max = circuit_fail_max
        self._circuit_reset_sec = circuit_reset_sec

        self._routing_override: dict[str, list[str]] = {}
        self._lock = RLock()

    # ------------------------------------------------------------------
    # Trainer-facing: reorder models per tier
    # ------------------------------------------------------------------
    def set_routing_preference(self, tier: str, ordered_models: list[str]) -> None:
        """Let the Trainer override routing order for a tier at runtime.

        Enforces the data-sovereignty invariant: no non-local model can be
        inserted into the restricted tier even by a compromised Trainer.
        Models not already present in the spec's tier list are rejected so
        the Trainer cannot smuggle in a provider that was never declared.
        """
        allowed = set(self._spec.routing_for(tier))
        unknown = [m for m in ordered_models if m not in allowed]
        if unknown:
            raise DataSovereigntyViolation(
                message=(
                    f"set_routing_preference({tier!r}) tried to add models "
                    f"not declared in the spec: {unknown}"
                ),
                downstream="sentinel",
                context={"tier": tier, "unknown_models": unknown},
            )
        if tier == "restricted":
            foreign = [m for m in ordered_models if not _is_local_model(m)]
            if foreign:
                raise DataSovereigntyViolation(
                    message=(
                        "set_routing_preference('restricted') must only contain "
                        f"local models; got: {foreign}"
                    ),
                    downstream="sentinel",
                    context={"tier": tier, "foreign_models": foreign},
                )
        with self._lock:
            self._routing_override[tier] = list(ordered_models)
        _logger.info("gateway.routing_updated", tier=tier, models=ordered_models)

    def get_routing(self, tier: str) -> list[str]:
        with self._lock:
            if tier in self._routing_override:
                return list(self._routing_override[tier])
        return self._spec.routing_for(tier)

    # ------------------------------------------------------------------
    # Core async API
    # ------------------------------------------------------------------
    async def aclassify(self, text: str) -> str:
        return self._classifier.classify(text)

    async def acompletion(
        self,
        messages: list[ChatMessage],
        *,
        data_tier: str | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> LLMResponse:
        """Run an LLM completion through the full Sentinel pipeline."""
        metadata = dict(metadata or {})
        with _tracer.start_as_current_span("sentinel.completion") as span:
            # Step 1: classify
            join_text = " ".join(m.content for m in messages if m.role == "user")
            tier = data_tier or await self.aclassify(join_text)
            span.set_attribute("stc.data_tier", tier)

            # Step 2: redact PII on user messages (may raise DataSovereigntyViolation)
            redacted_messages: list[ChatMessage] = []
            total_redactions = 0
            entity_counts: dict[str, int] = {}
            for m in messages:
                if m.role == "user":
                    result = self._redactor.redact(m.content)
                    redacted_messages.append(ChatMessage(role=m.role, content=result.text))
                    total_redactions += len(result.redactions)
                    for k, v in result.entity_counts.items():
                        entity_counts[k] = entity_counts.get(k, 0) + v
                else:
                    redacted_messages.append(m)
            span.set_attribute("stc.redactions", total_redactions)

            # Step 3: tokenize (optional; redaction masks PII, tokenization
            # provides reversible surrogates for values callers may want back)
            if self._tokenizer is not None and tier == "restricted":
                redacted_messages = [
                    ChatMessage(role=m.role, content=self._tokenizer.tokenize(m.content))
                    if m.role == "user"
                    else m
                    for m in redacted_messages
                ]

            # Step 4: route
            models = self.get_routing(tier)
            if not models:
                raise TierRoutingError(
                    message=f"No models configured for data tier {tier!r}",
                    context={"tier": tier},
                )

            # Data-sovereignty enforcement, defence-in-depth layer 3 of 3.
            # The other two layers:
            #   1. spec/models.py::_validate_routing_tiers — at spec load
            #   2. set_routing_preference — when Trainer reorders
            # A reviewer's instinct is "this is redundant; pick one".
            # It isn't. #1 runs once per spec load and doesn't observe
            # per-request tier classification. #2 protects against
            # declared-but-reordered models. THIS layer catches any
            # path where a restricted-tier query reaches dispatch with
            # a foreign model in the candidate list — e.g. a Trainer
            # that subclassed the gateway and mutated internal state,
            # or a future refactor that adds a fourth routing source.
            # Removing this block is a compliance regression that unit
            # tests alone cannot catch.
            if tier == "restricted":
                foreign = [m for m in models if not _is_local_model(m)]
                if foreign:
                    raise DataSovereigntyViolation(
                        message=(
                            "Restricted-tier routing includes external models; "
                            "refusing to dispatch."
                        ),
                        downstream="sentinel",
                        context={"tier": tier, "foreign_models": foreign},
                    )

            span.set_attribute("stc.models_candidate", ",".join(models))

            primary, *fallbacks = models

            async def _call(model: str) -> LLMResponse:
                circuit = get_circuit(
                    f"llm:{model}",
                    fail_max=self._circuit_fail_max,
                    reset_timeout=self._circuit_reset_sec,
                )

                async def _inner() -> LLMResponse:
                    async with self._bulkhead.acquire():
                        async with atimeout(self._timeout):
                            return await self._llm.acompletion(
                                model=model,
                                messages=redacted_messages,
                                timeout=self._timeout,
                                metadata=metadata,
                            )

                return await circuit.call(lambda: with_retry(
                    _inner, downstream=f"llm:{model}", max_attempts=self._max_attempts
                ))

            response = await run_with_fallback(
                lambda: _call(primary),
                [lambda m=m: _call(m) for m in fallbacks],
                label=f"llm:tier={tier}",
            )

            # Step 5: detokenize response if we tokenized on the way in
            if self._tokenizer is not None and tier == "restricted":
                response.content = self._tokenizer.detokenize_text(response.content)

            # Step 6: audit + metrics
            crossing = tier != "restricted" and not _is_local_model(response.model)
            if crossing:
                get_metrics().boundary_crossings_total.labels(
                    from_tier=tier, to_model=response.model
                ).inc()

            metrics = get_metrics()
            metrics.llm_tokens_total.labels(
                model=response.model, direction="prompt"
            ).inc(response.usage.prompt_tokens)
            metrics.llm_tokens_total.labels(
                model=response.model, direction="completion"
            ).inc(response.usage.completion_tokens)
            if response.cost_usd:
                metrics.cost_usd_total.labels(
                    model=response.model, tenant=tenant_id or "unknown"
                ).inc(response.cost_usd)

            if self._audit is not None:
                corr = current_correlation()
                await self._audit.emit(
                    AuditRecord(
                        trace_id=corr.get("trace_id"),
                        request_id=corr.get("request_id"),
                        tenant_id=tenant_id or corr.get("tenant_id"),
                        persona=corr.get("persona") or "stalwart",
                        event_type="llm_call",
                        spec_version=self._spec.version,
                        data_tier=tier,
                        boundary_crossing=crossing,
                        model=response.model,
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        cost_usd=response.cost_usd,
                        redactions=total_redactions,
                        redaction_entities=list(entity_counts.keys()),
                    )
                )

            span.set_attribute("stc.model_used", response.model)
            span.set_attribute("stc.boundary_crossing", crossing)
            return response

    # ------------------------------------------------------------------
    # Sync facade (uses asyncio.run; detects running loop)
    # ------------------------------------------------------------------
    def completion(
        self,
        messages: list[ChatMessage],
        *,
        data_tier: str | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> LLMResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.acompletion(
                    messages,
                    data_tier=data_tier,
                    metadata=metadata,
                    tenant_id=tenant_id,
                )
            )
        raise RuntimeError(
            "completion() cannot be called from a running event loop; "
            "use `await acompletion(...)` instead."
        )


__all__ = [
    "CircuitBreakerOpen",
    "DataSovereigntyViolation",
    "LLMError",
    "SentinelGateway",
    "TierRoutingError",
]
