from datetime import datetime, timedelta, timezone

from stc_framework.critic.escalation import EscalationManager
from stc_framework.critic.validators.base import GovernanceVerdict, GuardrailResult
from stc_framework.resilience.degradation import DegradationLevel, DegradationState


def _verdict(critical_failures: int) -> GovernanceVerdict:
    return GovernanceVerdict(
        trace_id="t",
        passed=critical_failures == 0,
        results=[
            GuardrailResult(
                rail_name=f"r{i}", passed=False, severity="critical", action="block"
            )
            for i in range(critical_failures)
        ],
        action="block" if critical_failures else "pass",
    )


def test_degraded_after_two_critical_in_window(minimal_spec):
    state = DegradationState()
    mgr = EscalationManager(minimal_spec.critic.escalation, degradation_state=state)
    for _ in range(10):
        mgr.record_result(_verdict(0))
    # Two critical failures in window (last 10)
    mgr.record_result(_verdict(1))
    mgr.record_result(_verdict(1))
    assert state.level >= DegradationLevel.DEGRADED


def test_consecutive_failures_trip_circuit_breaker(minimal_spec):
    state = DegradationState()
    mgr = EscalationManager(minimal_spec.critic.escalation, degradation_state=state)
    # 3 consecutive critical failures → PAUSED
    for _ in range(3):
        mgr.record_result(_verdict(1))
    assert state.level == DegradationLevel.PAUSED


def test_cooldown_resets_after_elapsed(minimal_spec):
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]

    def clock():
        return now[0]

    state = DegradationState()
    mgr = EscalationManager(
        minimal_spec.critic.escalation, clock=clock, degradation_state=state
    )
    for _ in range(3):
        mgr.record_result(_verdict(1))
    assert state.level == DegradationLevel.PAUSED

    # Advance past cooldown (60s in minimal spec)
    now[0] = now[0] + timedelta(seconds=120)
    mgr.record_result(_verdict(0))
    assert state.level == DegradationLevel.NORMAL
