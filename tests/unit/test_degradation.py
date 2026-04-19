from stc_framework.resilience.degradation import (
    DegradationLevel,
    DegradationState,
    get_degradation_state,
)


def test_degradation_starts_normal():
    state = DegradationState()
    assert state.level == DegradationLevel.NORMAL
    assert state.allow_traffic()


def test_degradation_listeners_fire():
    state = DegradationState()
    fired = []

    def listener(prev, new):
        fired.append((prev, new))

    state.subscribe(listener)
    state.set(DegradationLevel.DEGRADED, source="test", reason="x")
    state.set(DegradationLevel.NORMAL, source="test")
    assert fired[0][0] == DegradationLevel.NORMAL
    assert fired[0][1] == DegradationLevel.DEGRADED


def test_paused_blocks_traffic():
    state = DegradationState()
    state.set(DegradationLevel.PAUSED, source="test")
    assert not state.allow_traffic()
    assert state.is_paused()


def test_from_string_accepts_known_aliases():
    assert DegradationLevel.from_string("suspension") == DegradationLevel.PAUSED
    assert DegradationLevel.from_string("NORMAL") == DegradationLevel.NORMAL
    assert DegradationLevel.from_string("bogus") == DegradationLevel.NORMAL


def test_singleton_lifecycle():
    a = get_degradation_state()
    b = get_degradation_state()
    assert a is b
