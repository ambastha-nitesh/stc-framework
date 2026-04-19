"""STCSystem — the single public entrypoint.

What this solves
----------------
A caller with a query and a tenant id wants a governed response. This
module is the only place in the library that knows how to sequence the
defensive controls (input limits, idempotency, rate limit, budget,
input rails, Stalwart pipeline, output rails, audit, settle) in the
correct order. Everything else is an implementation detail.

Why `aquery` is 10 steps and cannot be "simplified"
---------------------------------------------------
The order of operations IS the design. Each step is a load-bearing
defensive control and each depends on its predecessors:

1. Type / size check — protects every downstream consumer from
   unbounded input.
2. Header sanitisation — prevents CR/LF injection into audit logs.
3. Idempotency cache — makes retries safe; must run before we count,
   charge, or audit.
4. ``_stopping`` check — graceful shutdown refuses new work.
5. Degradation guard — Critic-driven escalation short-circuits traffic.
6. Rate limit — token-bucket per tenant; retryable rejection.
7. Budget reserve — atomic with enforcement (closes a TOCTOU race).
8. Correlation binding — downstream logs/spans pivot on the same ids.
9. Input rails — reject injection / malicious input before LLM spend.
10. Pipeline — Stalwart + Sentinel + Critic output rails + audit + settle.

Reordering any of these is almost always a regression — the test
files :file:`tests/unit/test_staff_review*.py` will catch most of them.

Concurrency contract
--------------------
- ``STCSystem`` is thread-safe and re-entrant. One instance per process
  is the supported deployment; two instances in one process share
  global singletons (see ``docs/security/STAFF_REVIEW.md`` Tier-2 S9).
- All public ``a*`` methods are coroutines and must be awaited.
- ``query(...)`` is the sync facade and refuses to run inside a
  running event loop.

Startup invariants (prod only)
------------------------------
``astart()`` under ``STC_ENV=prod`` enforces six fail-closed invariants
(audit HMAC key, strict tokenization, no content logs, no mock LLM,
WORM backend, signed spec). Missing any one raises ``STCError`` so
Kubernetes readiness probes fail before the pod enters the pool.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

from contextlib import AsyncExitStack

from stc_framework.adapters.audit_backend.base import AuditBackend
from stc_framework.adapters.audit_backend.local_file import JSONLAuditBackend
from stc_framework.adapters.audit_backend.worm import (
    ComplianceViolation,
    WORMAuditBackend,
)
from stc_framework.adapters.embeddings.base import EmbeddingsClient
from stc_framework.adapters.embeddings.hash_embedder import HashEmbedder
from stc_framework.adapters.llm.base import LLMClient
from stc_framework.adapters.llm.mock import MockLLMClient
from stc_framework.adapters.prompts.base import PromptRecord, PromptRegistry
from stc_framework.adapters.prompts.file_registry import FilePromptRegistry
from stc_framework.adapters.vector_store.base import VectorStore
from stc_framework.adapters.vector_store.in_memory import InMemoryVectorStore
from stc_framework.config.logging import configure_logging, get_logger
from stc_framework.config.settings import STCSettings, get_settings
from stc_framework.critic.critic import Critic
from stc_framework.critic.validators.base import GovernanceVerdict
from stc_framework.errors import STCError
from stc_framework.governance.budget import TenantBudgetExceeded, TenantBudgetTracker
from stc_framework.governance.events import AuditEvent
from stc_framework.governance.idempotency import IdempotencyCache
from stc_framework.governance.rate_limit import RateLimitExceeded, TenantRateLimiter
from stc_framework.observability.audit import (
    AuditLogger,
    AuditRecord,
    _KeyManager as _AuditKeyManager,
)
from stc_framework.observability.correlation import bind_correlation, new_request_id
from stc_framework.observability.health import HealthReport, probe_system
from stc_framework.observability.inflight import InflightTracker
from stc_framework.observability.metrics import (
    get_metrics,
    init_metrics,
    start_metrics_server,
    tenant_label,
)
from stc_framework.observability.tracing import get_tracer, init_tracing
from stc_framework.reference_impl.financial_qa.prompts import FINANCIAL_QA_SYSTEM_PROMPT
from stc_framework.resilience.degradation import (
    DegradationLevel,
    DegradationState,
    get_degradation_state,
)
from stc_framework.security.limits import get_security_limits
from stc_framework.security.sanitize import (
    sanitize_header_value,
    strip_zero_width,
)
from stc_framework.sentinel.classifier import DataClassifier
from stc_framework.sentinel.gateway import SentinelGateway
from stc_framework.sentinel.redaction import PIIRedactor
from stc_framework.sentinel.token_store import InMemoryTokenStore
from stc_framework.sentinel.tokenization import Tokenizer
from stc_framework.spec.loader import load_spec
from stc_framework.spec.signing import SpecSignatureError, verify_spec_signature
from stc_framework.spec.models import STCSpec
from stc_framework.stalwart.agent import StalwartAgent
from stc_framework.stalwart.state import StalwartResult
from stc_framework.trainer.trainer import Trainer

_logger = get_logger(__name__)


@dataclass
class QueryResult:
    trace_id: str
    response: str
    governance: dict[str, Any]
    optimization: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SystemStats:
    total_queries: int = 0
    passed: int = 0
    blocked: int = 0
    warnings: int = 0

    def pass_rate(self) -> float:
        return self.passed / max(self.total_queries, 1)


class STCSystem:
    """Runtime container and entrypoint for the STC Framework."""

    def __init__(
        self,
        spec: STCSpec,
        *,
        settings: STCSettings | None = None,
        llm: LLMClient | None = None,
        vector_store: VectorStore | None = None,
        embeddings: EmbeddingsClient | None = None,
        prompt_registry: PromptRegistry | None = None,
        audit_backend: AuditBackend | None = None,
        degradation: DegradationState | None = None,
    ) -> None:
        self._spec = spec
        self._settings = settings or get_settings()
        configure_logging(
            level=self._settings.log_level,
            fmt=self._settings.log_format,
            log_content=self._settings.log_content,
        )
        init_tracing(
            service_name=self._settings.service_name,
            service_version=self._settings.service_version,
            otlp_endpoint=self._settings.otlp_endpoint,
            spec_version=spec.version,
        )
        init_metrics()

        self._llm = llm or MockLLMClient()
        self._vectors = vector_store or InMemoryVectorStore()
        self._embeddings = embeddings or HashEmbedder()
        self._prompts = prompt_registry or self._build_default_prompts()
        self._audit = AuditLogger(
            audit_backend or self._build_default_audit_backend()
        )

        self._classifier = DataClassifier(
            spec, presidio_enabled=self._settings.presidio_enabled
        )
        self._redactor = PIIRedactor(spec, presidio_enabled=self._settings.presidio_enabled)
        self._tokenizer = (
            Tokenizer(InMemoryTokenStore(), reversible=True)
            if spec.sentinel.tokenization.enabled
            else None
        )

        self._gateway = SentinelGateway(
            spec,
            self._llm,
            redactor=self._redactor,
            classifier=self._classifier,
            tokenizer=self._tokenizer,
            audit=self._audit,
            llm_timeout_sec=self._settings.llm_timeout_sec,
            llm_max_attempts=self._settings.llm_retry_max_attempts,
            llm_bulkhead=self._settings.llm_bulkhead,
            circuit_fail_max=self._settings.llm_circuit_fail_max,
            circuit_reset_sec=self._settings.llm_circuit_reset_sec,
        )

        self._stalwart = StalwartAgent(
            spec=spec,
            gateway=self._gateway,
            vector_store=self._vectors,
            embeddings=self._embeddings,
            prompt_registry=self._prompts,
            classifier=self._classifier,
            embedding_timeout_sec=self._settings.embedding_timeout_sec,
            vector_timeout_sec=self._settings.vector_timeout_sec,
            embedding_bulkhead=self._settings.embedding_bulkhead,
            vector_bulkhead=self._settings.vector_bulkhead,
            chunk_redactor=self._redactor,
        )
        self._critic = Critic(spec, redactor=self._redactor)
        self._trainer = Trainer(
            spec, self._gateway, self._prompts, audit=self._audit
        )
        self._degradation = degradation or get_degradation_state()

        # Enterprise readiness primitives ---------------------------------
        thresholds = spec.trainer.cost_thresholds
        self._budget = TenantBudgetTracker(
            per_task_usd=thresholds.max_per_task_usd,
            daily_usd=thresholds.daily_budget_usd,
            monthly_usd=thresholds.monthly_budget_usd,
        )
        self._idempotency = IdempotencyCache()
        self._inflight = InflightTracker()
        self._rate_limiter = TenantRateLimiter(
            rps=self._settings.tenant_rps,
            burst=self._settings.tenant_burst or None,
        )

        # Expose static info so `up{job="stc"}` dashboards have context.
        get_metrics().system_info.labels(
            service_version=self._settings.service_version,
            spec_version=spec.version,
            env=self._settings.env,
        ).set(1)

        self._stats = SystemStats()
        self._lock = RLock()
        self._started = False
        self._stopping = False

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------
    @classmethod
    def from_spec(cls, path: str | Path, **kwargs: Any) -> "STCSystem":
        return cls(load_spec(path), **kwargs)

    @classmethod
    def from_env(cls, **kwargs: Any) -> "STCSystem":
        settings = get_settings()
        return cls.from_spec(settings.spec_path, settings=settings, **kwargs)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def astart(
        self, *, strict_health: bool = False, health_timeout: float = 2.0
    ) -> None:
        """Start the system.

        When ``STCSettings.env == "prod"`` the startup also enforces the
        regulatory-readiness invariants ("fail-closed"): real HMAC key,
        strict tokenization, no content-in-logs, signed spec, a
        non-mock LLM, and a WORM-shaped audit backend. Deploying with
        defaults into a regulated environment now requires an explicit
        opt-out of each individual check.
        """
        with self._lock:
            if self._started:
                return
            self._started = True

        self._enforce_startup_invariants(strict_health=strict_health)

        if self._settings.metrics_enabled:
            try:
                start_metrics_server(port=self._settings.metrics_port)
            except OSError as exc:  # Port in use in tests, etc.
                _logger.warning("system.metrics_server_skipped", error=repr(exc))

        # Warm adapters that have expensive lazy initialisation.
        await self._warm_adapters()

        # Prime the adapter_healthcheck gauge so dashboards show something
        # immediately after the process starts; also fail fast if strict.
        report = await probe_system(self, timeout=health_timeout)
        if strict_health and not report.ok:
            failed = ", ".join(a.name for a in report.adapters if not a.ok)
            raise STCError(
                message=f"startup health check failed: {failed}",
                retryable=False,
            )
        await self._audit.emit(
            AuditRecord(
                persona="system",
                event_type=AuditEvent.SYSTEM_START.value,
                spec_version=self._spec.version,
                extra={
                    "ok": report.ok,
                    "adapters": [
                        {"name": a.name, "ok": a.ok} for a in report.adapters
                    ],
                },
            )
        )

    async def astop(self, *, drain_timeout: float = 30.0) -> bool:
        """Graceful shutdown.

        Waits up to ``drain_timeout`` seconds for in-flight queries to
        finish, closes every adapter that exposes ``aclose()``, then
        closes the audit log. Returns ``True`` on clean drain.
        """
        self._stopping = True
        drained = await self._inflight.wait_idle(timeout=drain_timeout)

        # Give every adapter a chance to release connections. We swallow
        # individual failures so one broken adapter cannot prevent the
        # others from closing.
        for name, adapter in (
            ("llm", self._llm),
            ("vector_store", self._vectors),
            ("embeddings", self._embeddings),
            ("prompt_registry", self._prompts),
        ):
            aclose = getattr(adapter, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception as exc:  # pragma: no cover - best effort
                    _logger.warning(
                        "system.adapter_close_failed",
                        adapter=name,
                        error=repr(exc),
                    )

        try:
            await self._audit.emit(
                AuditRecord(
                    persona="system",
                    event_type=AuditEvent.SYSTEM_STOP.value,
                    spec_version=self._spec.version,
                    extra={"drained": drained, "inflight": self._inflight.current},
                )
            )
        finally:
            await self._audit.close()
        return drained

    async def ahealth_probe(self, *, timeout: float = 2.0) -> HealthReport:
        """Probe every adapter and return an aggregated :class:`HealthReport`."""
        return await probe_system(self, timeout=timeout)

    # ------------------------------------------------------------------
    # Startup hardening
    # ------------------------------------------------------------------

    def _enforce_startup_invariants(self, *, strict_health: bool) -> None:
        """Fail-closed invariants for regulated deployments.

        - In ``prod`` mode every check is mandatory.
        - In ``staging`` mode we warn loudly but do not block.
        - In ``dev`` mode we only validate signatures when explicitly
          configured.
        """
        env = self._settings.env
        is_prod = env == "prod"

        # 1. Audit HMAC key must not be ephemeral.
        if is_prod and _AuditKeyManager.is_ephemeral():
            raise STCError(
                message=(
                    "STC_AUDIT_HMAC_KEY must be set in prod; refusing to boot "
                    "with an ephemeral audit HMAC key (chain integrity would "
                    "not survive restart)."
                ),
                retryable=False,
            )

        # 2. Tokenization must be strict (missing tokenization key fails
        # closed instead of silently generating a per-process key).
        if is_prod and not os.getenv("STC_TOKENIZATION_STRICT", "").lower() in {
            "1",
            "true",
            "yes",
        }:
            raise STCError(
                message=(
                    "STC_TOKENIZATION_STRICT must be enabled in prod so a "
                    "missing tokenization key fails closed."
                ),
                retryable=False,
            )

        # 3. Content logging must not leak in prod.
        if is_prod and self._settings.log_content:
            raise STCError(
                message="STC_LOG_CONTENT must be false in prod.",
                retryable=False,
            )

        # 4. No mock LLM in prod.
        if is_prod and self._settings.llm_adapter == "mock":
            raise STCError(
                message="STC_LLM_ADAPTER=mock is not allowed in prod.",
                retryable=False,
            )

        # 5. Audit backend must be WORM-shaped in prod.
        if is_prod and not isinstance(self._audit.backend, WORMAuditBackend):
            raise STCError(
                message=(
                    "prod requires a WORM-shaped audit backend; set "
                    "STC_AUDIT_BACKEND=worm or inject WORMAuditBackend."
                ),
                retryable=False,
            )

        # 6. Spec signature must verify in prod.
        try:
            verify_spec_signature(
                self._settings.spec_path,
                required=is_prod,
            )
        except SpecSignatureError as exc:
            raise STCError(
                message=f"spec signature check failed: {exc}",
                retryable=False,
            ) from exc

        if not is_prod and _AuditKeyManager.is_ephemeral():
            _logger.warning(
                "system.audit_key_ephemeral",
                note="chain cannot be verified across process restarts",
            )

    async def _warm_adapters(self) -> None:
        """Force expensive lazy initialisation at startup.

        Currently only Presidio's spaCy model — calling ``analyze()``
        once warms the pipeline so the first customer query doesn't pay
        the ~1 s cold-start penalty.
        """
        redactor = getattr(self, "_redactor", None)
        if redactor is None:
            return
        try:
            # Run on a thread — Presidio is synchronous.
            await asyncio.to_thread(redactor.redact, "warmup")
        except Exception as exc:  # pragma: no cover - warmup is best-effort
            _logger.info("system.presidio_warmup_skipped", error=repr(exc))

    # ------------------------------------------------------------------
    # Query APIs
    # ------------------------------------------------------------------
    async def aquery(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> QueryResult:
        """Submit a query and get back a governed response.

        Runs the 10-step pipeline described in the module docstring.
        Emits audit records for every significant event, Prometheus
        metrics, and OpenTelemetry spans — the caller does not need to
        instrument anything.

        Contract
        --------
        - **Inputs** must validate: ``query`` is a non-empty string <=
          :attr:`SecurityLimits.max_query_chars` (8 KB by default);
          ``tenant_id`` and ``idempotency_key``, if provided, are
          sanitised to header-safe ASCII.
        - **Output** is a :class:`QueryResult` whose ``governance``
          field reports the final action (``pass``, ``warn``, ``block``,
          ``block_input``, ``escalate``). The ``response`` field is
          always a user-facing string, even when blocked.
        - **Idempotency**: a repeated ``(tenant_id, idempotency_key)``
          returns the cached result without re-spending the tenant's
          budget or emitting duplicate audit events.
        - **Invariants**: never spends LLM budget on a query that fails
          the input rails; never returns ``pass`` when any critical
          rail failed; never charges a tenant for a crashed pipeline.

        Side effects
        ------------
        - Writes between 3 and 8 audit records depending on outcome.
        - Increments ``stc_queries_total``, ``stc_stage_latency_ms``,
          and ``stc_governance_events_total``.
        - May mutate degradation state if the Critic escalates.
        - Reserves, then settles, budget against the tenant's rolling
          window.

        Failure modes
        -------------
        Raises :class:`STCError` for:

        - ``query`` wrong type or over size limit (``retryable=False``).
        - System is shutting down (``retryable=True``; client should
          retry once the new process is up).
        - Degradation state is ``PAUSED``.
        - Rate limit exceeded (``retryable=True``; exponential backoff).
        - Tenant budget exhausted (``retryable=False`` until window
          rolls over).

        The Stalwart's own errors are caught inside the pipeline; they
        surface as ``result.metadata["error"]`` with the exception
        class name only (exception message is suppressed to avoid
        echoing user content into logs).

        Usage
        -----
        >>> system = STCSystem.from_env()
        >>> await system.astart()
        >>> result = await system.aquery(
        ...     "What was Acme FY2024 revenue?",
        ...     tenant_id="acme-corp",
        ...     idempotency_key="req-42",
        ... )
        >>> if result.governance["action"] == "pass":
        ...     print(result.response)
        """
        await self.astart()

        # Boundary validation — reject obviously abusive input before any
        # downstream work is done. These are hard caps, not heuristics.
        limits = get_security_limits()
        if not isinstance(query, str):
            raise STCError(message="query must be a string", retryable=False)
        if len(query) > limits.max_query_chars:
            raise STCError(
                message=(
                    f"query exceeds maximum allowed length "
                    f"({len(query)} > {limits.max_query_chars})"
                ),
                retryable=False,
            )
        # Strip zero-width / BiDi override characters up front so every
        # downstream validator sees the same normalized string.
        query = strip_zero_width(query)

        # Sanitize tenant_id so later log lines cannot be forged by
        # injecting CR/LF into the header value.
        if tenant_id is not None:
            tenant_id = sanitize_header_value(
                tenant_id, limit=limits.max_header_value_chars
            )
        if idempotency_key is not None:
            idempotency_key = sanitize_header_value(
                idempotency_key, limit=limits.max_header_value_chars
            )

        # Idempotency short-circuit: if the caller supplied a key we've
        # already seen, return the cached result instead of re-charging
        # the tenant and re-emitting audit records.
        if idempotency_key:
            cached = self._idempotency.get(tenant_id, idempotency_key)
            if cached is not None:
                return cached

        if self._stopping:
            raise STCError(
                message="System is shutting down; rejecting new requests",
                retryable=True,
            )

        if not self._degradation.allow_traffic():
            raise STCError(
                message=f"System paused (level={self._degradation.level.name})",
                retryable=False,
            )

        # Per-tenant RPS cap — disabled when tenant_rps == 0. Rate-limit
        # failures are retryable: the caller should back off and retry.
        try:
            self._rate_limiter.acquire(tenant_id)
        except RateLimitExceeded as exc:
            raise STCError(
                message=str(exc),
                retryable=True,
                context={"reason": "tenant_rate_limit_exceeded"},
            ) from exc

        # Per-tenant budget enforcement. Atomic reserve (book the worst-
        # case per-task cost up front) closes the TOCTOU window: two
        # concurrent requests that would both fit individually but not
        # together both get past a plain ``enforce`` and charge after.
        reserved = float(self._spec.trainer.cost_thresholds.max_per_task_usd or 0.0)
        try:
            if tenant_id and reserved > 0:
                self._budget.reserve(tenant_id, anticipated_cost=reserved)
            else:
                self._budget.enforce(tenant_id or "")
        except TenantBudgetExceeded as exc:
            get_metrics().tenant_budget_rejections_total.labels(
                tenant=tenant_label(tenant_id), window=exc.window
            ).inc()
            await self._audit.emit(
                AuditRecord(
                    tenant_id=tenant_id,
                    persona="system",
                    event_type=AuditEvent.QUERY_REJECTED.value,
                    action="budget_exceeded",
                    extra={
                        "window": exc.window,
                        "observed_usd": exc.observed,
                        "limit_usd": exc.limit,
                    },
                )
            )
            raise STCError(
                message=str(exc),
                retryable=False,
                context={"reason": "tenant_budget_exceeded"},
            ) from exc

        with self._lock:
            self._stats.total_queries += 1
            n = self._stats.total_queries

        request_id = new_request_id()
        trace_id = f"stc-{int(time.time())}-{n:06d}"

        tracer = get_tracer(__name__)

        async with self._inflight.track():
          with bind_correlation(
            trace_id=trace_id, request_id=request_id, tenant_id=tenant_id, persona="stalwart"
          ):
            # Parent span for the whole query so every downstream span
            # (gateway.completion, stalwart.run, critic.*) hangs off one
            # trace tree.
            with tracer.start_as_current_span("stc.aquery") as span:
                span.set_attribute("stc.trace_id", trace_id)
                span.set_attribute("stc.request_id", request_id)
                span.set_attribute("stc.tenant_id", tenant_id or "")
                span.set_attribute("stc.spec_version", self._spec.version)

                try:
                    result = await self._run_pipeline(
                        query=query,
                        tenant_id=tenant_id,
                        trace_id=trace_id,
                        request_id=request_id,
                        span=span,
                    )
                except BaseException:
                    # Refund the budget reservation if the pipeline
                    # exploded before settling it. Never leave a tenant
                    # billed for a crashed request.
                    if tenant_id and reserved > 0:
                        self._budget.settle(
                            tenant_id, reserved=reserved, actual=0.0
                        )
                    raise

                if idempotency_key:
                    self._idempotency.put(tenant_id, idempotency_key, result)
                return result

    async def _run_pipeline(
        self,
        *,
        query: str,
        tenant_id: str | None,
        trace_id: str,
        request_id: str,
        span: Any,
    ) -> "QueryResult":
        metrics = get_metrics()
        tenant_lbl = tenant_label(tenant_id)

        # Every query is audited, regardless of outcome.
        await self._audit.emit(
            AuditRecord(
                trace_id=trace_id,
                request_id=request_id,
                tenant_id=tenant_id,
                persona="system",
                event_type=AuditEvent.QUERY_ACCEPTED.value,
                spec_version=self._spec.version,
                extra={"query_len": len(query)},
            )
        )

        # Input rails — gate before we spend any LLM budget
        t0 = time.perf_counter()
        input_verdict = await self._critic.aevaluate_input(query, trace_id=trace_id)
        metrics.stage_latency_ms.labels(stage="input_rails").observe(
            (time.perf_counter() - t0) * 1000
        )
        if input_verdict.action == "block":
            await self._audit_rail_failures(
                input_verdict, trace_id=trace_id, tenant_id=tenant_id, stage="input"
            )
            await self._audit.emit(
                AuditRecord(
                    trace_id=trace_id,
                    request_id=request_id,
                    tenant_id=tenant_id,
                    persona="critic",
                    event_type=AuditEvent.QUERY_REJECTED.value,
                    action="block",
                    rail_results=[
                        {
                            "name": r.rail_name,
                            "passed": r.passed,
                            "severity": r.severity,
                        }
                        for r in input_verdict.results
                    ],
                )
            )
            metrics.queries_total.labels(
                persona="system", tenant=tenant_lbl, action="block_input"
            ).inc()
            span.set_attribute("stc.action", "block_input")
            # Refund the reservation — no LLM was actually called.
            if tenant_id:
                reserved_cost = float(
                    self._spec.trainer.cost_thresholds.max_per_task_usd or 0.0
                )
                if reserved_cost > 0:
                    self._budget.settle(
                        tenant_id, reserved=reserved_cost, actual=0.0
                    )
            return self._build_blocked_result(query, input_verdict, trace_id)

        # Stalwart (classify + retrieve + reason)
        t0 = time.perf_counter()
        stalwart: StalwartResult = await self._stalwart.arun(
            query, trace_id=trace_id, tenant_id=tenant_id
        )
        metrics.stage_latency_ms.labels(stage="stalwart").observe(
            (time.perf_counter() - t0) * 1000
        )

        # Output rails
        t0 = time.perf_counter()
        verdict = await self._critic.aevaluate_output(
            {
                "trace_id": trace_id,
                "query": stalwart.query,
                "response": stalwart.response,
                "context": stalwart.context,
                "retrieved_chunks": stalwart.retrieved_chunks,
                "data_tier": stalwart.data_tier,
            }
        )
        metrics.stage_latency_ms.labels(stage="output_rails").observe(
            (time.perf_counter() - t0) * 1000
        )

        # Audit every rail failure individually, then the overall
        # query completion event.
        await self._audit_rail_failures(
            verdict, trace_id=trace_id, tenant_id=tenant_id, stage="output"
        )
        await self._audit.emit(
            AuditRecord(
                trace_id=trace_id,
                request_id=request_id,
                tenant_id=tenant_id,
                persona="system",
                event_type=AuditEvent.QUERY_COMPLETED.value,
                spec_version=self._spec.version,
                data_tier=stalwart.data_tier,
                model=stalwart.model_used,
                action=verdict.action,
                escalation_level=verdict.escalation_level,
                cost_usd=stalwart.cost_usd,
                prompt_tokens=stalwart.prompt_tokens,
                completion_tokens=stalwart.completion_tokens,
                rail_results=[
                    {
                        "name": r.rail_name,
                        "passed": r.passed,
                        "severity": r.severity,
                    }
                    for r in verdict.results
                ],
            )
        )

        final_response = self._resolve_response(stalwart, verdict)

        # Settle the reservation with the real LLM spend so the rolling
        # budget reflects actual cost rather than the pessimistic per-task
        # ceiling we booked up front.
        if tenant_id:
            reserved_cost = float(
                self._spec.trainer.cost_thresholds.max_per_task_usd or 0.0
            )
            if reserved_cost > 0:
                self._budget.settle(
                    tenant_id,
                    reserved=reserved_cost,
                    actual=stalwart.cost_usd or 0.0,
                )
            elif stalwart.cost_usd:
                self._budget.record_cost(tenant_id, stalwart.cost_usd)
            metrics.tenant_budget_usd.labels(
                tenant=tenant_lbl, window="daily"
            ).set(self._budget.observed(tenant_id, window="daily"))

        # Trainer ingests a trace *without* raw user content so the
        # history store cannot become a secondary PII reservoir.
        trace_for_trainer = {
            "trace_id": stalwart.trace_id,
            "model_used": stalwart.model_used,
            "retrieval_scores": stalwart.retrieval_scores,
            "cost_usd": stalwart.cost_usd,
            "latency_ms": stalwart.latency_ms,
            "data_tier": stalwart.data_tier,
            "prompt_version": stalwart.prompt_version,
            "tenant_id": tenant_id,
            "hallucination_detected": not verdict.passed,
            "accuracy": 1.0 if verdict.passed else 0.0,
        }
        transition = await self._trainer.on_trace(trace_for_trainer)

        metrics.queries_total.labels(
            persona="stalwart", tenant=tenant_lbl, action=verdict.action
        ).inc()
        metrics.latency_ms.labels(persona="stalwart", stage="total").observe(
            stalwart.latency_ms
        )

        span.set_attribute("stc.action", verdict.action)
        span.set_attribute("stc.model_used", stalwart.model_used)

        return QueryResult(
            trace_id=trace_id,
            response=final_response,
            governance={
                "passed": verdict.passed,
                "action": verdict.action,
                "escalation_level": verdict.escalation_level,
                "rail_results": [
                    {
                        "name": r.rail_name,
                        "passed": r.passed,
                        "severity": r.severity,
                        "details": r.details,
                    }
                    for r in verdict.results
                ],
            },
            optimization={
                "reward": transition.reward,
                "signals": transition.signals,
            },
            metadata={
                "request_id": request_id,
                "model_used": stalwart.model_used,
                "data_tier": stalwart.data_tier,
                "spec_version": stalwart.spec_version,
                "prompt_version": stalwart.prompt_version,
                "citations": stalwart.citations,
                "cost_usd": stalwart.cost_usd,
                "latency_ms": stalwart.latency_ms,
                "error": stalwart.error,
            },
        )

    def query(self, query: str, *, tenant_id: str | None = None) -> QueryResult:
        """Synchronous facade; not usable from inside a running event loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aquery(query, tenant_id=tenant_id))
        raise RuntimeError(
            "STCSystem.query() cannot be called inside a running event loop; "
            "use `await STCSystem.aquery(...)` instead."
        )

    # ------------------------------------------------------------------
    # Other public methods
    # ------------------------------------------------------------------
    def submit_feedback(self, trace_id: str, feedback: str) -> None:
        self._trainer.on_user_feedback(trace_id, feedback)
        # Audit the feedback itself — feedback influences the Trainer's
        # optimization and must be traceable in a dispute.
        self._audit.emit_sync(
            AuditRecord(
                trace_id=trace_id,
                persona="system",
                event_type=AuditEvent.FEEDBACK_SUBMITTED.value,
                action=feedback,
            )
        )

    # ------------------------------------------------------------------
    # Governance facade — DSAR, right-to-erasure, retention.
    # ------------------------------------------------------------------
    async def aexport_tenant(self, tenant_id: str) -> dict[str, Any]:
        """Produce a DSAR export for ``tenant_id``."""
        from stc_framework.governance import export_tenant_records

        record = await export_tenant_records(self, tenant_id)
        return {
            "tenant_id": record.tenant_id,
            "exported_at": record.exported_at,
            "audit_records": record.audit_records,
            "history_records": record.history_records,
            "vector_documents": record.vector_documents,
            "prompt_registrations": record.prompt_registrations,
        }

    async def aerase_tenant(self, tenant_id: str) -> dict[str, int]:
        """Erase every record the STC system holds for ``tenant_id``."""
        from stc_framework.governance import erase_tenant

        summary = await erase_tenant(self, tenant_id)
        return {
            "tenant_id": summary.tenant_id,
            "audit_removed": summary.audit_removed,
            "history_removed": summary.history_removed,
            "vector_removed": summary.vector_removed,
            "tokens_removed": summary.tokens_removed,
        }

    async def aapply_retention(self) -> dict[str, int]:
        """Apply ``audit.retention_days`` across every store."""
        from stc_framework.governance import apply_retention

        summary = await apply_retention(self)
        return {
            "retention_days": summary.retention_days,
            "audit_removed": summary.audit_removed,
            "history_removed": summary.history_removed,
            "tokens_removed": summary.tokens_removed,
        }

    async def _audit_rail_failures(
        self,
        verdict: GovernanceVerdict,
        *,
        trace_id: str,
        tenant_id: str | None,
        stage: str,
    ) -> None:
        for r in verdict.results:
            if r.passed:
                continue
            await self._audit.emit(
                AuditRecord(
                    trace_id=trace_id,
                    tenant_id=tenant_id,
                    persona="critic",
                    event_type=AuditEvent.RAIL_FAILED.value,
                    action=r.action,
                    spec_version=self._spec.version,
                    rail_results=[
                        {
                            "name": r.rail_name,
                            "passed": False,
                            "severity": r.severity,
                            "stage": stage,
                        }
                    ],
                    extra={"details": r.details[:512]},
                )
            )

    async def ahealth_check(self) -> dict[str, Any]:
        trainer_report = await self._trainer.run_health_check()
        with self._lock:
            stats = {
                "total_queries": self._stats.total_queries,
                "passed": self._stats.passed,
                "blocked": self._stats.blocked,
                "warnings": self._stats.warnings,
                "pass_rate": self._stats.pass_rate(),
            }
        return {
            "system": self._spec.name,
            "version": self._spec.version,
            "status": trainer_report.get("status", "unknown"),
            "degradation": self._degradation.snapshot(),
            "stats": stats,
            "trainer": trainer_report,
            "escalation_level": self._critic.escalation.current_level,
        }

    def health_check(self) -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ahealth_check())
        raise RuntimeError("health_check() cannot be called from a running event loop")

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    @property
    def spec(self) -> STCSpec:
        return self._spec

    @property
    def gateway(self) -> SentinelGateway:
        return self._gateway

    @property
    def trainer(self) -> Trainer:
        return self._trainer

    @property
    def critic(self) -> Critic:
        return self._critic

    @property
    def stalwart(self) -> StalwartAgent:
        return self._stalwart

    @property
    def vector_store(self) -> VectorStore:
        return self._vectors

    @property
    def embeddings(self) -> EmbeddingsClient:
        return self._embeddings

    @property
    def prompt_registry(self) -> PromptRegistry:
        return self._prompts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_default_audit_backend(self) -> AuditBackend:
        """Construct the audit backend indicated by ``STC_AUDIT_BACKEND``."""
        choice = self._settings.audit_backend
        if choice == "worm":
            return WORMAuditBackend(directory=self._settings.audit_path)
        return JSONLAuditBackend(directory=self._settings.audit_path)

    def _build_default_prompts(self) -> PromptRegistry:
        registry = FilePromptRegistry()
        registry.seed(
            [
                PromptRecord(
                    name="stalwart_system",
                    version="v1.0",
                    content=FINANCIAL_QA_SYSTEM_PROMPT,
                    active=True,
                )
            ]
        )
        return registry

    def _resolve_response(
        self, stalwart: StalwartResult, verdict: GovernanceVerdict
    ) -> str:
        with self._lock:
            if verdict.action == "pass":
                self._stats.passed += 1
                return stalwart.response
            if verdict.action == "warn":
                self._stats.warnings += 1
                return (
                    stalwart.response
                    + "\n\nNote: This response has been flagged for review. Please "
                    "verify critical figures against source documents."
                )
            if verdict.action == "block":
                self._stats.blocked += 1
                # Return the *names* of the rails that failed, not their
                # free-text details — rail details sometimes echo matched
                # substrings that originated from the request, and
                # reflecting those back to the caller is an avoidable
                # information-disclosure risk.
                rail_names = sorted(
                    r.rail_name
                    for r in verdict.results
                    if not r.passed and r.severity == "critical"
                )
                return (
                    "I was unable to generate a verified answer to your question. "
                    f"The response was blocked by governance checks: {', '.join(rail_names)}. "
                    "Please rephrase your question or consult the source documents directly."
                )
            if verdict.action == "escalate":
                self._stats.blocked += 1
                lvl = DegradationLevel.from_string(verdict.escalation_level or "degraded")
                if lvl >= DegradationLevel.PAUSED:
                    return (
                        "This system has been paused due to repeated governance "
                        "failures. Human review is required before the system can resume."
                    )
                if lvl == DegradationLevel.QUARANTINE:
                    return (
                        "This response is being held for human review before delivery."
                    )
                return (
                    stalwart.response
                    + "\n\nDEGRADED MODE: this system is operating with reduced "
                    "confidence. All figures should be independently verified."
                )
            return stalwart.response

    def _build_blocked_result(
        self, query: str, verdict: GovernanceVerdict, trace_id: str
    ) -> QueryResult:
        with self._lock:
            self._stats.blocked += 1
        return QueryResult(
            trace_id=trace_id,
            response="I cannot process this request; it was blocked at the input rails.",
            governance={
                "passed": False,
                "action": "block",
                "escalation_level": None,
                "rail_results": [
                    {
                        "name": r.rail_name,
                        "passed": r.passed,
                        "severity": r.severity,
                        "details": r.details,
                    }
                    for r in verdict.results
                ],
            },
            optimization={"reward": 0.0, "signals": []},
            metadata={"query": "<redacted>"},
        )
