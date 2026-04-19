"""Aggregated health / readiness probe.

Calls ``healthcheck`` on every adapter exposed by the :class:`STCSystem`
with a short timeout and returns a single report. ``/readyz`` renders
this; operators can poll it via :meth:`STCSystem.ahealth_probe` without
hitting any LLM provider.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stc_framework.observability.metrics import get_metrics


@dataclass
class AdapterHealth:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class HealthReport:
    ok: bool
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    adapters: list[AdapterHealth] = field(default_factory=list)
    degradation_level: str = "normal"
    inflight_requests: int = 0


async def _probe(name: str, coro: Any, timeout: float) -> AdapterHealth:
    try:
        # wait_for works on every supported Python version (3.10+)
        # unlike asyncio.timeout which is 3.11+.
        result = await asyncio.wait_for(coro, timeout=timeout)
        ok = bool(result)
        detail = "healthy" if ok else "adapter returned falsy"
    except asyncio.TimeoutError:
        ok = False
        detail = "healthcheck timed out"
    except Exception as exc:
        ok = False
        detail = f"{type(exc).__name__}: {exc}"
    metrics = get_metrics()
    metrics.adapter_healthcheck.labels(adapter=name).set(1 if ok else 0)
    return AdapterHealth(name=name, ok=ok, detail=detail)


async def probe_system(system: Any, *, timeout: float = 2.0) -> HealthReport:
    """Probe every adapter on ``system`` and return an aggregated report."""
    probes: list[tuple[str, Any]] = []

    for name, attr in (
        ("llm", getattr(system, "_llm", None)),
        ("vector_store", getattr(system, "vector_store", None)),
        ("embeddings", getattr(system, "embeddings", None)),
        ("prompt_registry", getattr(system, "prompt_registry", None)),
    ):
        if attr is not None and hasattr(attr, "healthcheck"):
            probes.append((name, attr.healthcheck()))

    adapters = (
        await asyncio.gather(*[_probe(n, c, timeout) for n, c in probes])
        if probes
        else []
    )

    degradation = getattr(system, "_degradation", None)
    degradation_level = (
        degradation.level.name.lower() if degradation is not None else "normal"
    )
    inflight = 0
    tracker = getattr(system, "_inflight", None)
    if tracker is not None:
        inflight = tracker.current

    overall_ok = all(a.ok for a in adapters) and degradation_level != "paused"
    return HealthReport(
        ok=overall_ok,
        adapters=adapters,
        degradation_level=degradation_level,
        inflight_requests=inflight,
    )
