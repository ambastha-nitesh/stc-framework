"""Tests for FR-9 rate limits + spend cap projection."""

from __future__ import annotations

import time

import pytest

from stc_framework.ai_hub.errors import AIHubErrorCode
from stc_framework.ai_hub.rate_limits import (
    AgentRateLimiter,
    RateLimitExceeded,
    SpendCapExceeded,
    SpendCapProjector,
    TPMWindow,
)

# ---------- TPMWindow -----------------------------------------------------


def test_tpm_window_evicts_old_samples() -> None:
    w = TPMWindow()
    # t0 sample lands outside the rolling window by the time we ask.
    w.record(500, now=1000.0)
    assert w.current_sum(now=1000.0) == 500
    assert w.current_sum(now=1061.0) == 0  # 61s later


def test_tpm_window_keeps_in_window_samples() -> None:
    w = TPMWindow()
    w.record(100, now=1000.0)
    w.record(200, now=1030.0)
    assert w.current_sum(now=1040.0) == 300


# ---------- AgentRateLimiter — RPM ---------------------------------------


def test_rpm_allows_under_limit() -> None:
    rl = AgentRateLimiter()
    for i in range(5):
        rl.check_rpm("agent-1", rpm_limit=10, now=1000.0 + i * 0.1)
        rl.record_request("agent-1", now=1000.0 + i * 0.1)


def test_rpm_rejects_over_limit_with_retry_after() -> None:
    rl = AgentRateLimiter()
    for i in range(60):
        rl.check_rpm("agent-1", rpm_limit=60, now=1000.0 + i * 0.5)
        rl.record_request("agent-1", now=1000.0 + i * 0.5)
    # 61st request within the same 60s window should trip the limit.
    with pytest.raises(RateLimitExceeded) as ei:
        rl.check_rpm("agent-1", rpm_limit=60, now=1029.5)
    assert ei.value.code is AIHubErrorCode.RATE_LIMIT_RPM
    assert ei.value.http_status == 429
    assert ei.value.extra["retry_after_seconds"] >= 1


def test_rpm_resets_after_window_slides() -> None:
    rl = AgentRateLimiter()
    for i in range(60):
        rl.record_request("agent-1", now=1000.0 + i * 0.1)
    # 60s later the old hits have aged out; a fresh call is allowed.
    rl.check_rpm("agent-1", rpm_limit=60, now=1080.0)


def test_rpm_per_agent_isolation() -> None:
    rl = AgentRateLimiter()
    for i in range(10):
        rl.record_request("agent-a", now=1000.0 + i * 0.1)
    # Different agent has its own window.
    rl.check_rpm("agent-b", rpm_limit=5, now=1001.0)


# ---------- AgentRateLimiter — TPM ---------------------------------------


def test_tpm_projection_allows_within_limit() -> None:
    rl = AgentRateLimiter()
    rl.record_tokens("agent-1", tokens=20_000, now=1000.0)
    rl.check_tpm_projection(
        "agent-1",
        projected_tokens=10_000,
        tpm_limit=100_000,
        now=1001.0,
    )


def test_tpm_projection_rejects_when_over_cap() -> None:
    rl = AgentRateLimiter()
    rl.record_tokens("agent-1", tokens=95_000, now=1000.0)
    with pytest.raises(RateLimitExceeded) as ei:
        rl.check_tpm_projection(
            "agent-1",
            projected_tokens=10_000,
            tpm_limit=100_000,
            now=1001.0,
        )
    assert ei.value.code is AIHubErrorCode.RATE_LIMIT_TPM


def test_tpm_expired_samples_free_capacity() -> None:
    rl = AgentRateLimiter()
    rl.record_tokens("agent-1", tokens=95_000, now=1000.0)
    # 61 seconds later the sample is gone.
    rl.check_tpm_projection(
        "agent-1",
        projected_tokens=50_000,
        tpm_limit=100_000,
        now=1061.0,
    )


def test_tpm_negative_projection_raises() -> None:
    rl = AgentRateLimiter()
    with pytest.raises(ValueError):
        rl.check_tpm_projection("a", projected_tokens=-1, tpm_limit=100)


def test_usage_helpers_return_window_values() -> None:
    rl = AgentRateLimiter()
    rl.record_request("a", now=1000.0)
    rl.record_request("a", now=1001.0)
    rl.record_tokens("a", tokens=500, now=1000.0)
    assert rl.rpm_usage("a", now=1002.0) == 2
    assert rl.tpm_usage("a", now=1002.0) == 500


# ---------- SpendCapProjector -------------------------------------------


def test_spend_projection_allows_within_cap() -> None:
    sp = SpendCapProjector()
    sp.register_domain("dom-1", monthly_cap_usd=100.0)
    sp.record_spend("dom-1", actual_cost_usd=50.0)
    sp.assert_within("dom-1", projected_cost_usd=25.0)


def test_spend_projection_rejects_over_cap() -> None:
    sp = SpendCapProjector()
    sp.register_domain("dom-1", monthly_cap_usd=100.0)
    sp.record_spend("dom-1", actual_cost_usd=80.0)
    with pytest.raises(SpendCapExceeded) as ei:
        sp.assert_within("dom-1", projected_cost_usd=30.0)
    assert ei.value.code is AIHubErrorCode.SPEND_CAP_EXCEEDED


def test_spend_override_extends_cap_until_expiry() -> None:
    sp = SpendCapProjector()
    sp.register_domain("dom-1", monthly_cap_usd=100.0)
    sp.record_spend("dom-1", actual_cost_usd=95.0)
    # Without override — projection blocks.
    with pytest.raises(SpendCapExceeded):
        sp.assert_within("dom-1", projected_cost_usd=10.0)
    # Platform Admin grants $50 override good for 1h.
    sp.grant_override("dom-1", additional_usd=50.0, expires_epoch=time.time() + 3600)
    # Now the projection fits.
    sp.assert_within("dom-1", projected_cost_usd=10.0)


def test_spend_override_expires() -> None:
    sp = SpendCapProjector()
    sp.register_domain("dom-1", monthly_cap_usd=100.0)
    sp.record_spend("dom-1", actual_cost_usd=95.0)
    # Override that expired an hour ago should NOT apply.
    sp.grant_override("dom-1", additional_usd=50.0, expires_epoch=time.time() - 3600)
    with pytest.raises(SpendCapExceeded):
        sp.assert_within("dom-1", projected_cost_usd=10.0)


def test_spend_record_returns_updated_mtd() -> None:
    sp = SpendCapProjector()
    sp.register_domain("dom-1", monthly_cap_usd=1000.0)
    new_total = sp.record_spend("dom-1", actual_cost_usd=12.5)
    assert new_total == pytest.approx(12.5)


def test_spend_zero_cost_is_noop() -> None:
    sp = SpendCapProjector()
    sp.register_domain("dom-1", monthly_cap_usd=1000.0)
    sp.record_spend("dom-1", actual_cost_usd=0.0)
    assert sp.snapshot("dom-1").month_to_date_usd == 0.0


def test_spend_unknown_domain_raises() -> None:
    sp = SpendCapProjector()
    with pytest.raises(KeyError):
        sp.assert_within("never-registered", projected_cost_usd=1.0)


def test_spend_negative_projection_rejected() -> None:
    sp = SpendCapProjector()
    sp.register_domain("dom-1", monthly_cap_usd=100.0)
    with pytest.raises(ValueError):
        sp.assert_within("dom-1", projected_cost_usd=-1.0)
