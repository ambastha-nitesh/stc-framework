"""Tests for :mod:`stc_framework.security.pen_testing`."""

from __future__ import annotations

import pytest

from stc_framework._internal.patterns import Pattern
from stc_framework.security.pen_testing import PenTestRunner, TestResult


async def _always_blocked_probe(_pattern: Pattern) -> str:
    return "blocked"


async def _always_allowed_probe(_pattern: Pattern) -> str:
    return "allowed"


@pytest.mark.asyncio
async def test_runner_blocked_defences_produce_fail_attack() -> None:
    runner = PenTestRunner(_always_blocked_probe)
    results = await runner.run_all()
    assert all(r.result is TestResult.FAIL for r in results)
    assert len(results) > 0


@pytest.mark.asyncio
async def test_runner_allowed_probes_produce_pass_attack() -> None:
    runner = PenTestRunner(_always_allowed_probe)
    results = await runner.run_all()
    assert all(r.result is TestResult.PASS for r in results)


@pytest.mark.asyncio
async def test_runner_captures_mitre_owasp() -> None:
    runner = PenTestRunner(_always_blocked_probe)
    results = await runner.run_all()
    # At least one default payload should be tagged with MITRE + OWASP.
    assert any(r.mitre for r in results)
    assert any(r.owasp for r in results)


@pytest.mark.asyncio
async def test_runner_summary_totals_match_results() -> None:
    runner = PenTestRunner(_always_blocked_probe)
    results = await runner.run_all()
    summary = PenTestRunner.summarise(results)
    assert summary["total"] == len(results)
    # FAIL count equals full suite since the probe always blocked.
    assert summary["counts"]["fail"] == len(results)


@pytest.mark.asyncio
async def test_runner_error_path_captured() -> None:
    async def bad_probe(_pattern: Pattern) -> str:
        raise RuntimeError("probe failed")

    runner = PenTestRunner(bad_probe)
    results = await runner.run_all()
    assert all(r.result is TestResult.ERROR for r in results)
