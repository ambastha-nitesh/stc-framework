"""Performance testing + SLO validation.

A small framework for running load profiles against an async probe and
validating the measured latencies / error rates / throughput against
declared SLOs.

Scope is deliberately minimal — this is not a replacement for k6 /
Locust. It is enough to:

* Simulate four :class:`LoadProfile` levels (baseline / peak / stress /
  soak) against any async ``probe_fn``.
* Collect p50/p95/p99 latencies, success/error counts, realized RPS.
* Compare each measurement to a list of :class:`SLODefinition` and
  report violations.
* Track regression vs. the previous run (via KeyValueStore).

Every SLO violation emits :data:`AuditEvent.SLO_VIOLATION` and
increments ``stc_slo_violations_total``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from statistics import mean
from typing import Any

from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord
from stc_framework.observability.metrics import get_metrics


class LoadProfile(str, Enum):
    BASELINE = "baseline"
    PEAK = "peak"
    STRESS = "stress"
    SOAK = "soak"


@dataclass
class LoadConfig:
    profile: LoadProfile
    rps: float
    duration_seconds: float
    ramp_seconds: float = 0.0


DEFAULT_PROFILES: dict[LoadProfile, LoadConfig] = {
    LoadProfile.BASELINE: LoadConfig(profile=LoadProfile.BASELINE, rps=5.0, duration_seconds=30.0),
    LoadProfile.PEAK: LoadConfig(profile=LoadProfile.PEAK, rps=50.0, duration_seconds=60.0, ramp_seconds=10.0),
    LoadProfile.STRESS: LoadConfig(profile=LoadProfile.STRESS, rps=200.0, duration_seconds=60.0, ramp_seconds=15.0),
    LoadProfile.SOAK: LoadConfig(profile=LoadProfile.SOAK, rps=25.0, duration_seconds=600.0),
}


@dataclass
class SLODefinition:
    name: str
    sli_description: str = ""
    target: float = 0.0
    unit: str = "ms"  # ms | pct | rps | ratio
    measurement: str = "p95"  # p50 | p95 | p99 | mean | error_rate | rps
    direction: str = "higher_is_worse"  # "higher_is_worse" for latency; "lower_is_worse" for availability/rps
    error_budget_period_days: int = 30


# Seven ships-by-default SLOs covering the common bases.
DEFAULT_SLOS: tuple[SLODefinition, ...] = (
    SLODefinition(name="latency_p50_ms", target=300.0, measurement="p50"),
    SLODefinition(name="latency_p95_ms", target=1500.0, measurement="p95"),
    SLODefinition(name="latency_p99_ms", target=3000.0, measurement="p99"),
    SLODefinition(name="error_rate", target=0.01, unit="ratio", measurement="error_rate"),
    SLODefinition(name="throughput_rps", target=10.0, unit="rps", measurement="rps", direction="lower_is_worse"),
)


@dataclass
class MetricsReport:
    samples: int = 0
    errors: int = 0
    total_seconds: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)

    def record(self, duration_ms: float, *, error: bool) -> None:
        self.samples += 1
        if error:
            self.errors += 1
        else:
            self.latencies_ms.append(duration_ms)

    def summary(self) -> dict[str, float]:
        if self.samples == 0:
            return {
                "samples": 0,
                "errors": 0,
                "error_rate": 0.0,
                "rps": 0.0,
                "mean": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "p99": 0.0,
            }
        sorted_lat = sorted(self.latencies_ms)
        n = len(sorted_lat)
        mean_ms = mean(sorted_lat) if sorted_lat else 0.0
        p50 = sorted_lat[int(n * 0.5) - 1] if sorted_lat else 0.0
        p95 = sorted_lat[max(int(n * 0.95) - 1, 0)] if sorted_lat else 0.0
        p99 = sorted_lat[max(int(n * 0.99) - 1, 0)] if sorted_lat else 0.0
        return {
            "samples": float(self.samples),
            "errors": float(self.errors),
            "error_rate": self.errors / self.samples,
            "rps": self.samples / max(self.total_seconds, 1e-6),
            "mean": mean_ms,
            "p50": p50,
            "p95": p95,
            "p99": p99,
        }


@dataclass
class SLOValidation:
    slo: SLODefinition
    measured: float
    violated: bool


def validate_slos(summary: dict[str, float], slos: list[SLODefinition]) -> list[SLOValidation]:
    out: list[SLOValidation] = []
    for slo in slos:
        key = slo.measurement
        measured = float(summary.get(key, 0.0))
        violated = measured > slo.target if slo.direction == "higher_is_worse" else measured < slo.target
        out.append(SLOValidation(slo=slo, measured=measured, violated=violated))
    return out


# Probe function signature: async, receives no args, returns None on success.
ProbeFn = Callable[[], Awaitable[None]]


class PerformanceTestRunner:
    """Runs a load profile against a probe and validates SLOs."""

    def __init__(
        self,
        probe_fn: ProbeFn,
        *,
        slos: list[SLODefinition] | None = None,
        audit: AuditLogger | None = None,
        store: KeyValueStore | None = None,
    ) -> None:
        self._probe = probe_fn
        self._slos = list(slos) if slos is not None else list(DEFAULT_SLOS)
        self._audit = audit
        self._store = store

    async def run_load_test(self, config: LoadConfig) -> dict[str, Any]:
        report = MetricsReport()
        start = time.perf_counter()
        interval = 1.0 / max(config.rps, 0.1)
        deadline = start + config.duration_seconds

        async def one_call() -> None:
            t0 = time.perf_counter()
            errored = False
            try:
                await self._probe()
            except Exception:
                errored = True
            finally:
                report.record((time.perf_counter() - t0) * 1000.0, error=errored)

        tasks: list[asyncio.Task[None]] = []
        while time.perf_counter() < deadline:
            tasks.append(asyncio.create_task(one_call()))
            await asyncio.sleep(interval)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        report.total_seconds = time.perf_counter() - start

        summary = report.summary()
        validations = validate_slos(summary, self._slos)
        violated = [v for v in validations if v.violated]
        out = {
            "profile": config.profile.value,
            "rps_target": config.rps,
            "duration_seconds": round(report.total_seconds, 3),
            "summary": summary,
            "violations": [
                {
                    "slo": v.slo.name,
                    "target": v.slo.target,
                    "measured": v.measured,
                    "direction": v.slo.direction,
                }
                for v in violated
            ],
            "validations": [
                {
                    "slo": v.slo.name,
                    "target": v.slo.target,
                    "measured": v.measured,
                    "violated": v.violated,
                }
                for v in validations
            ],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        for v in violated:
            try:
                get_metrics().slo_violations_total.labels(slo_name=v.slo.name).inc()
            except Exception:
                pass
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    event_type=AuditEvent.LOAD_TEST_COMPLETED.value,
                    persona="infrastructure",
                    extra={
                        "profile": config.profile.value,
                        "violation_count": len(violated),
                        "summary": summary,
                    },
                )
            )
            for v in violated:
                await self._audit.emit(
                    AuditRecord(
                        event_type=AuditEvent.SLO_VIOLATION.value,
                        persona="infrastructure",
                        extra={
                            "slo": v.slo.name,
                            "target": v.slo.target,
                            "measured": v.measured,
                        },
                    )
                )
        if self._store is not None:
            await self._store.set(f"perf:last_run:{config.profile.value}", out)
        return out

    async def regression_check(self, current: dict[str, Any], *, percent_threshold: float = 10.0) -> dict[str, Any]:
        """Compare ``current`` against the stored previous run; flag regressions."""
        if self._store is None:
            return {"available": False, "reason": "no store configured"}
        prev = await self._store.get(f"perf:last_run:{current['profile']}")
        if not prev:
            return {"available": False, "reason": "no previous run"}
        regressions: list[dict[str, Any]] = []
        prev_summary = prev.get("summary", {})
        cur_summary = current.get("summary", {})
        for key in ("p50", "p95", "p99", "error_rate"):
            p = float(prev_summary.get(key, 0.0))
            c = float(cur_summary.get(key, 0.0))
            if p <= 0:
                continue
            delta_pct = ((c - p) / p) * 100.0
            if delta_pct > percent_threshold:
                regressions.append(
                    {
                        "metric": key,
                        "previous": p,
                        "current": c,
                        "delta_percent": round(delta_pct, 2),
                    }
                )
        return {
            "available": True,
            "threshold_percent": percent_threshold,
            "regressions": regressions,
            "regression_count": len(regressions),
        }

    @staticmethod
    def capacity_model(*, measured_rps: float, target_rps: float, safety_margin: float = 0.3) -> dict[str, Any]:
        """Headroom + safety margin check. Pure function, no IO."""
        required = target_rps * (1.0 + safety_margin)
        headroom = measured_rps - required
        return {
            "measured_rps": measured_rps,
            "target_rps": target_rps,
            "required_with_margin": required,
            "headroom_rps": headroom,
            "sufficient": headroom >= 0.0,
        }


__all__ = [
    "DEFAULT_PROFILES",
    "DEFAULT_SLOS",
    "LoadConfig",
    "LoadProfile",
    "MetricsReport",
    "PerformanceTestRunner",
    "SLODefinition",
    "SLOValidation",
    "validate_slos",
]
