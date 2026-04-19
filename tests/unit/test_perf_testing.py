"""Tests for :mod:`stc_framework.infrastructure.perf_testing`."""

from __future__ import annotations

import asyncio

import pytest

from stc_framework.infrastructure.perf_testing import (
    DEFAULT_SLOS,
    LoadConfig,
    LoadProfile,
    MetricsReport,
    PerformanceTestRunner,
    SLODefinition,
    validate_slos,
)
from stc_framework.infrastructure.store import InMemoryStore


def test_metrics_report_percentiles_on_uniform_samples() -> None:
    report = MetricsReport(total_seconds=10.0)
    for i in range(1, 101):
        report.record(float(i), error=False)
    summary = report.summary()
    assert summary["samples"] == 100
    assert summary["errors"] == 0
    assert summary["p50"] == pytest.approx(50.0, abs=1.0)
    assert summary["p95"] == pytest.approx(95.0, abs=1.0)
    assert summary["p99"] == pytest.approx(99.0, abs=1.0)


def test_metrics_report_error_rate() -> None:
    report = MetricsReport(total_seconds=1.0)
    report.record(10.0, error=False)
    report.record(10.0, error=True)
    assert report.summary()["error_rate"] == 0.5


def test_validate_slos_latency_violation() -> None:
    summary = {"p95": 2000.0, "error_rate": 0.001, "rps": 50.0, "p50": 400.0, "p99": 2500.0}
    validations = validate_slos(summary, list(DEFAULT_SLOS))
    p95 = next(v for v in validations if v.slo.name == "latency_p95_ms")
    assert p95.violated is True


def test_validate_slos_throughput_violation() -> None:
    summary = {"p95": 100.0, "error_rate": 0.0, "rps": 1.0, "p50": 50.0, "p99": 200.0}
    validations = validate_slos(summary, list(DEFAULT_SLOS))
    rps = next(v for v in validations if v.slo.name == "throughput_rps")
    # Measured 1 rps vs target 10 rps, lower_is_worse -> violated.
    assert rps.violated is True


@pytest.mark.asyncio
async def test_runner_executes_probe_and_reports_summary() -> None:
    call_count = {"n": 0}

    async def probe() -> None:
        call_count["n"] += 1
        await asyncio.sleep(0.001)

    runner = PerformanceTestRunner(probe_fn=probe)
    result = await runner.run_load_test(LoadConfig(profile=LoadProfile.BASELINE, rps=50.0, duration_seconds=0.1))
    assert result["profile"] == "baseline"
    assert call_count["n"] > 0
    assert result["summary"]["samples"] > 0


@pytest.mark.asyncio
async def test_runner_tracks_errors() -> None:
    async def failing_probe() -> None:
        raise RuntimeError("boom")

    slos = [SLODefinition(name="error_rate", target=0.01, unit="ratio", measurement="error_rate")]
    runner = PerformanceTestRunner(probe_fn=failing_probe, slos=slos)
    result = await runner.run_load_test(LoadConfig(profile=LoadProfile.BASELINE, rps=20.0, duration_seconds=0.1))
    # Error rate is 100% -> violates the 1% target.
    assert result["summary"]["error_rate"] == pytest.approx(1.0)
    assert any(v["slo"] == "error_rate" for v in result["violations"])


@pytest.mark.asyncio
async def test_regression_check_requires_previous_run() -> None:
    async def probe() -> None:
        await asyncio.sleep(0.001)

    runner = PerformanceTestRunner(probe_fn=probe, store=InMemoryStore())
    result = await runner.run_load_test(LoadConfig(profile=LoadProfile.BASELINE, rps=20.0, duration_seconds=0.1))
    check = await runner.regression_check(result)
    # First run stored; regression check has no baseline yet vs what's saved.
    assert check["available"] is True
    assert check["regressions"] == []


def test_capacity_model_positive_headroom() -> None:
    out = PerformanceTestRunner.capacity_model(measured_rps=30.0, target_rps=20.0, safety_margin=0.3)
    assert out["sufficient"] is True
    assert out["headroom_rps"] == pytest.approx(30.0 - 26.0)


def test_capacity_model_insufficient_headroom() -> None:
    out = PerformanceTestRunner.capacity_model(measured_rps=15.0, target_rps=20.0, safety_margin=0.3)
    assert out["sufficient"] is False
