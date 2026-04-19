"""Tests for :mod:`stc_framework.governance.budget_controls` and anomaly."""

from __future__ import annotations

import pytest

from stc_framework.errors import OrchestrationError, WorkflowBudgetExhausted
from stc_framework.governance.anomaly import AnomalyConfig, CostAnomalyDetector
from stc_framework.governance.budget_controls import (
    BurstController,
    CostBreakerConfig,
    CostBreakerState,
    CostCircuitBreaker,
    TokenGovernor,
    TokenGovernorConfig,
    TokenLimitExceeded,
)

# ---------- TokenGovernor -------------------------------------------------


def test_token_governor_allows_within_caps() -> None:
    g = TokenGovernor(TokenGovernorConfig(max_input_tokens=100, max_output_tokens=50))
    g.check_input(input_tokens=50, max_output_tokens=20)  # no raise


def test_token_governor_rejects_over_input_cap() -> None:
    g = TokenGovernor(TokenGovernorConfig(max_input_tokens=100, max_output_tokens=50))
    with pytest.raises(TokenLimitExceeded):
        g.check_input(input_tokens=200)


def test_token_governor_rejects_over_output_cap() -> None:
    g = TokenGovernor(TokenGovernorConfig(max_input_tokens=100, max_output_tokens=50))
    with pytest.raises(TokenLimitExceeded):
        g.check_input(input_tokens=10, max_output_tokens=100)


def test_token_governor_persona_quota_enforced() -> None:
    g = TokenGovernor(TokenGovernorConfig(daily_tokens_per_persona=100))
    g.check_persona_quota("stalwart")  # no usage yet
    g.record_usage("stalwart", tokens_used=99)
    g.check_persona_quota("stalwart")  # just under
    g.record_usage("stalwart", tokens_used=2)
    with pytest.raises(TokenLimitExceeded):
        g.check_persona_quota("stalwart")


def test_token_governor_quota_disabled_by_default() -> None:
    g = TokenGovernor()
    g.record_usage("x", tokens_used=10_000_000)
    g.check_persona_quota("x")  # no raise when cap is None


# ---------- BurstController -----------------------------------------------


def test_burst_controller_allows_within_cap() -> None:
    b = BurstController(max_llm_calls_per_workflow=3)
    assert b.record_llm_call("wf-1") == 1
    assert b.record_llm_call("wf-1") == 2
    assert b.record_llm_call("wf-1") == 3


def test_burst_controller_raises_when_exceeded() -> None:
    b = BurstController(max_llm_calls_per_workflow=2)
    b.record_llm_call("wf-1")
    b.record_llm_call("wf-1")
    with pytest.raises(OrchestrationError):
        b.record_llm_call("wf-1")


def test_burst_controller_per_workflow_isolated() -> None:
    b = BurstController(max_llm_calls_per_workflow=2)
    b.record_llm_call("wf-a")
    b.record_llm_call("wf-b")
    b.record_llm_call("wf-a")
    # wf-b still has budget
    b.record_llm_call("wf-b")
    with pytest.raises(OrchestrationError):
        b.record_llm_call("wf-a")


def test_burst_controller_reset_clears_count() -> None:
    b = BurstController(max_llm_calls_per_workflow=2)
    b.record_llm_call("wf-1")
    b.record_llm_call("wf-1")
    b.reset("wf-1")
    assert b.count("wf-1") == 0
    b.record_llm_call("wf-1")  # no raise


# ---------- CostCircuitBreaker --------------------------------------------


def test_cost_breaker_classification_bands() -> None:
    cfg = CostBreakerConfig(
        daily_budget_usd=100.0,
        warn_at_percent=50.0,
        throttle_at_percent=75.0,
        pause_at_percent=90.0,
        halt_at_percent=100.0,
    )
    assert cfg.classify(0) is CostBreakerState.NORMAL
    assert cfg.classify(49) is CostBreakerState.NORMAL
    assert cfg.classify(50) is CostBreakerState.WARN
    assert cfg.classify(75) is CostBreakerState.THROTTLE
    assert cfg.classify(90) is CostBreakerState.PAUSE
    assert cfg.classify(100) is CostBreakerState.HALT


def test_cost_breaker_observe_records_history_on_transition() -> None:
    breaker = CostCircuitBreaker(CostBreakerConfig(daily_budget_usd=100.0))
    breaker.observe("stalwart", spent_usd=0)
    breaker.observe("stalwart", spent_usd=60)
    breaker.observe("stalwart", spent_usd=80)
    breaker.observe("stalwart", spent_usd=95)
    assert breaker.state("stalwart") is CostBreakerState.PAUSE


def test_cost_breaker_enforce_raises_on_halt() -> None:
    breaker = CostCircuitBreaker(CostBreakerConfig(daily_budget_usd=10.0))
    breaker.enforce("trainer", spent_usd=1.0)  # NORMAL
    breaker.enforce("trainer", spent_usd=5.0)  # WARN
    with pytest.raises(WorkflowBudgetExhausted):
        breaker.enforce("trainer", spent_usd=10.0)


# ---------- CostAnomalyDetector -------------------------------------------


def test_anomaly_detector_warmup_stays_green() -> None:
    d = CostAnomalyDetector(AnomalyConfig(min_samples=20))
    for _ in range(19):
        obs = d.observe("gpt-4", 0.01)
    # Still in warmup; rolling_mean is None.
    assert obs.rolling_mean is None
    assert obs.level.value == "green"


def test_anomaly_detector_flags_red_on_large_spike() -> None:
    d = CostAnomalyDetector(AnomalyConfig(min_samples=5, amber_multiplier=3.0, red_multiplier=5.0))
    for _ in range(6):
        d.observe("gpt-4", 0.01)
    obs = d.observe("gpt-4", 1.00)  # 100x the mean — well past red
    assert obs.level.value == "red"


def test_anomaly_detector_amber_on_moderate_spike() -> None:
    d = CostAnomalyDetector(AnomalyConfig(min_samples=5, amber_multiplier=3.0, red_multiplier=5.0))
    for _ in range(10):
        d.observe("gpt-4", 0.10)
    obs = d.observe("gpt-4", 0.40)  # 4x the mean — AMBER
    assert obs.level.value == "amber"


def test_anomaly_detector_rolling_mean_tracks_recent_cost() -> None:
    d = CostAnomalyDetector(AnomalyConfig(min_samples=3, window_size=5))
    for _ in range(5):
        d.observe("gpt-4", 0.10)
    assert d.rolling_mean("gpt-4") == pytest.approx(0.10)
    # Shift the window so new mean > old mean.
    for _ in range(5):
        d.observe("gpt-4", 0.20)
    assert d.rolling_mean("gpt-4") == pytest.approx(0.20)


def test_anomaly_detector_reset_drops_history() -> None:
    d = CostAnomalyDetector(AnomalyConfig(min_samples=1))
    d.observe("gpt-4", 0.5)
    assert d.rolling_mean("gpt-4") is not None
    d.reset("gpt-4")
    assert d.rolling_mean("gpt-4") is None
