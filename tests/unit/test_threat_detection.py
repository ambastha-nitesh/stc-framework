"""Tests for :mod:`stc_framework.security.threat_detection`."""

from __future__ import annotations

import pytest

from stc_framework.errors import DDoSDetected, HoneyTokenTriggered
from stc_framework.security.threat_detection import (
    BehavioralAnalyzer,
    BehavioralThresholds,
    DeceptionEngine,
    EdgeLimits,
    EdgeRateLimiter,
    ThreatDetectionManager,
    ThreatSeverity,
    ThreatType,
)


def test_rate_limiter_allows_under_caps() -> None:
    rl = EdgeRateLimiter(EdgeLimits(per_minute=5, per_hour=100))
    for _ in range(5):
        rl.check("1.2.3.4")


def test_rate_limiter_blocks_over_per_minute_cap() -> None:
    rl = EdgeRateLimiter(EdgeLimits(per_minute=3, per_hour=100))
    for _ in range(3):
        rl.check("1.2.3.4")
    with pytest.raises(DDoSDetected):
        rl.check("1.2.3.4")
    assert rl.is_blocked("1.2.3.4")


def test_rate_limiter_cost_exhaustion() -> None:
    rl = EdgeRateLimiter(EdgeLimits(per_minute=100, cost_exhaustion_usd_per_minute=0.50))
    # Single expensive call crosses the cost threshold.
    with pytest.raises(DDoSDetected) as ei:
        rl.check("x", cost_usd=0.75)
    assert ei.value.threat_type == ThreatType.DDOS_COST_EXHAUSTION.value


def test_behavioural_flags_high_firewall_block_rate() -> None:
    b = BehavioralAnalyzer(BehavioralThresholds(firewall_block_rate_red=0.5))
    for _ in range(10):
        b.record_query("s-1", blocked_by_firewall=True)
    alert = b.analyze_session("s-1")
    assert alert is not None
    assert alert.threat_type is ThreatType.PROMPT_INJECTION_CAMPAIGN


def test_behavioural_flags_extraction_by_query_count() -> None:
    b = BehavioralAnalyzer(BehavioralThresholds(session_query_count_extraction=5))
    for _ in range(5):
        b.record_query("s-1")
    alert = b.analyze_session("s-1")
    assert alert is not None
    assert alert.threat_type is ThreatType.MODEL_EXTRACTION


def test_behavioural_returns_none_for_clean_session() -> None:
    b = BehavioralAnalyzer()
    assert b.analyze_session("never-seen") is None
    b.record_query("clean", blocked_by_firewall=False, critic_failed=False)
    assert b.analyze_session("clean") is None


def test_deception_engine_triggers_on_honey_doc() -> None:
    d = DeceptionEngine()
    d.register_honey_doc("d-canary")
    alert = d.check_doc_access("d-canary")
    assert alert is not None
    assert alert.severity is ThreatSeverity.CRITICAL


def test_deception_engine_clean_token_returns_none() -> None:
    d = DeceptionEngine()
    d.register_honey_token("STC_TOK_honeyhoney")
    assert d.check_token_use("STC_TOK_legit0000") is None


def test_manager_honey_token_raises() -> None:
    mgr = ThreatDetectionManager()
    mgr.deception.register_honey_token("STC_TOK_honeyhoney")
    with pytest.raises(HoneyTokenTriggered):
        mgr.honey_token_used("STC_TOK_honeyhoney")


def test_manager_dashboard_counts_alerts() -> None:
    mgr = ThreatDetectionManager()
    mgr.deception.register_honey_doc("d-1")
    with pytest.raises(HoneyTokenTriggered):
        mgr.honey_doc_accessed("d-1")
    dash = mgr.dashboard()
    assert dash["total_alerts"] == 1
    assert ThreatType.HONEY_DOC_ACCESSED.value in dash["by_type"]
