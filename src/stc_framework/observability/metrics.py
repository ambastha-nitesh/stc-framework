"""Prometheus metrics for the STC Framework.

All metrics are created once and cached. The Prometheus registry is
``prometheus_client.REGISTRY`` by default; tests may pass their own
registry to :func:`init_metrics`.

Cardinality considerations
--------------------------
Every metric with a ``tenant`` label uses :func:`tenant_label`, which
hashes tenant IDs that are not in a short allow-list down to a
fixed-width hex prefix. This prevents a deployment with millions of
tenants from blowing up Prometheus storage while still letting
operators filter by tenant when the ID is known.

Add known low-cardinality tenant IDs to the allow-list by calling
:func:`set_known_tenants` at process start.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from threading import Lock

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, start_http_server
from prometheus_client.registry import REGISTRY as _DEFAULT_REGISTRY

_lock = Lock()
_metrics: STCMetrics | None = None
_server_started = False
_known_tenants: set[str] = set()


# Hard upper bound on the length of any tenant label we will expose to
# Prometheus. Longer IDs are hashed.
_TENANT_LABEL_MAX_LEN = 32


def set_known_tenants(tenants: set[str]) -> None:
    """Declare tenant IDs that are safe to expose verbatim as metric labels.

    IDs not in this set are hashed to an 8-char prefix so an unbounded
    tenant population cannot cause cardinality explosion.
    """
    global _known_tenants
    _known_tenants = set(tenants)


def tenant_label(tenant_id: str | None) -> str:
    """Return a Prometheus-safe label for a tenant ID."""
    if not tenant_id:
        return "unknown"
    if tenant_id in _known_tenants:
        return tenant_id
    if len(tenant_id) <= _TENANT_LABEL_MAX_LEN and all(c.isalnum() or c in "-_" for c in tenant_id):
        # Short, label-safe IDs pass through — useful in dev / tests.
        return tenant_id
    digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:8]
    return f"t-{digest}"


@dataclass
class STCMetrics:
    """Container for all STC Prometheus metrics."""

    queries_total: Counter
    latency_ms: Histogram
    stage_latency_ms: Histogram
    cost_usd_total: Counter
    guardrail_failures_total: Counter
    llm_tokens_total: Counter
    circuit_breaker_state: Gauge
    escalation_level: Gauge
    redaction_events_total: Counter
    boundary_crossings_total: Counter
    bulkhead_rejections_total: Counter
    retry_attempts_total: Counter
    # --- Governance / enterprise ------------------------------------
    governance_events_total: Counter
    tenant_budget_usd: Gauge
    tenant_budget_rejections_total: Counter
    adapter_healthcheck: Gauge
    system_info: Gauge
    inflight_requests: Gauge


_DEFAULT_BUCKETS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000)


def init_metrics(registry: CollectorRegistry | None = None) -> STCMetrics:
    """Create (or return cached) metrics bound to the given registry."""
    global _metrics
    with _lock:
        if _metrics is not None:
            return _metrics

        reg = registry or _DEFAULT_REGISTRY

        _metrics = STCMetrics(
            queries_total=Counter(
                "stc_queries_total",
                "Total number of queries processed by the STC System.",
                labelnames=("persona", "tenant", "action"),
                registry=reg,
            ),
            latency_ms=Histogram(
                "stc_latency_ms",
                "End-to-end request latency in milliseconds.",
                labelnames=("persona", "stage"),
                buckets=_DEFAULT_BUCKETS,
                registry=reg,
            ),
            stage_latency_ms=Histogram(
                "stc_stage_latency_ms",
                "Per-stage latency (classify, retrieve, reason, output_rails, ...) in ms.",
                labelnames=("stage",),
                buckets=_DEFAULT_BUCKETS,
                registry=reg,
            ),
            cost_usd_total=Counter(
                "stc_cost_usd_total",
                "Cumulative spend in USD by model and tenant.",
                labelnames=("model", "tenant"),
                registry=reg,
            ),
            guardrail_failures_total=Counter(
                "stc_guardrail_failures_total",
                "Count of guardrail failures by rail and severity.",
                labelnames=("rail", "severity"),
                registry=reg,
            ),
            llm_tokens_total=Counter(
                "stc_llm_tokens_total",
                "LLM tokens consumed.",
                labelnames=("model", "direction"),
                registry=reg,
            ),
            circuit_breaker_state=Gauge(
                "stc_circuit_breaker_state",
                "Circuit breaker state (0=closed, 1=half-open, 2=open).",
                labelnames=("downstream",),
                registry=reg,
            ),
            escalation_level=Gauge(
                "stc_escalation_level",
                "Critic escalation level (0=normal, 1=degraded, 2=quarantine, 3=suspension).",
                registry=reg,
            ),
            redaction_events_total=Counter(
                "stc_redaction_events_total",
                "PII redactions performed at the Sentinel.",
                labelnames=("entity_type",),
                registry=reg,
            ),
            boundary_crossings_total=Counter(
                "stc_boundary_crossings_total",
                "Data-tier boundary crossings (restricted → non-local).",
                labelnames=("from_tier", "to_model"),
                registry=reg,
            ),
            bulkhead_rejections_total=Counter(
                "stc_bulkhead_rejections_total",
                "Bulkhead rejections (queue full).",
                labelnames=("bulkhead",),
                registry=reg,
            ),
            retry_attempts_total=Counter(
                "stc_retry_attempts_total",
                "Retry attempts made by the resilience layer.",
                labelnames=("downstream", "outcome"),
                registry=reg,
            ),
            governance_events_total=Counter(
                "stc_governance_events_total",
                "Count of audited governance events by event_type.",
                labelnames=("event_type",),
                registry=reg,
            ),
            tenant_budget_usd=Gauge(
                "stc_tenant_budget_usd",
                "Observed spend for a tenant in the current window.",
                labelnames=("tenant", "window"),
                registry=reg,
            ),
            tenant_budget_rejections_total=Counter(
                "stc_tenant_budget_rejections_total",
                "Queries rejected for exceeding the tenant's cost budget.",
                labelnames=("tenant", "window"),
                registry=reg,
            ),
            adapter_healthcheck=Gauge(
                "stc_adapter_healthcheck",
                "Last healthcheck result for a named adapter (1 healthy, 0 unhealthy).",
                labelnames=("adapter",),
                registry=reg,
            ),
            system_info=Gauge(
                "stc_system_info",
                "Static info gauge exposing version / env / spec labels (value=1).",
                labelnames=("service_version", "spec_version", "env"),
                registry=reg,
            ),
            inflight_requests=Gauge(
                "stc_inflight_requests",
                "Number of queries currently being processed.",
                registry=reg,
            ),
        )
        return _metrics


def get_metrics() -> STCMetrics:
    """Return the initialized metrics, initializing defaults if needed."""
    return init_metrics()


def start_metrics_server(port: int = 9090, addr: str = "0.0.0.0") -> None:
    """Start the Prometheus exposition HTTP server (idempotent)."""
    global _server_started
    with _lock:
        if _server_started:
            return
        start_http_server(port, addr=addr)
        _server_started = True


def reset_metrics_for_tests(registry: CollectorRegistry | None = None) -> STCMetrics:
    """Reset metrics for tests. Requires a fresh registry to avoid collisions."""
    global _metrics, _server_started
    with _lock:
        _metrics = None
        _server_started = False
    return init_metrics(registry)
