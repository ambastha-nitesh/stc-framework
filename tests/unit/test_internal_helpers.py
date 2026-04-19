"""Unit tests for the ``stc_framework._internal`` helpers.

Phase 0 shared primitives: state machine, alerter, scoring, TTL, patterns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stc_framework._internal.alerter import (
    AlertLevel,
    ThresholdAlerter,
    Thresholds,
)
from stc_framework._internal.patterns import load_pattern_catalog
from stc_framework._internal.scoring import (
    ScoringError,
    WeightedScore,
    dimension_score,
    fairness_ratio,
    weighted_average,
)
from stc_framework._internal.state_machine import (
    IllegalTransition,
    StatefulRecord,
)
from stc_framework._internal.ttl import TTL, is_stale, now_iso

# ---------- state_machine --------------------------------------------------


def test_statemachine_permitted_transition_records_history() -> None:
    record: StatefulRecord[str] = StatefulRecord(state="draft")
    transitions = {"draft": {"active"}, "active": {"closed"}, "closed": set()}
    record.transition("active", transitions, actor="alice", reason="ready")
    assert record.state == "active"
    assert len(record.history) == 1
    assert record.history[0].from_state == "draft"
    assert record.history[0].to_state == "active"
    assert record.history[0].actor == "alice"


def test_statemachine_illegal_transition_raises() -> None:
    record: StatefulRecord[str] = StatefulRecord(state="draft")
    transitions = {"draft": {"active"}, "active": {"closed"}, "closed": set()}
    with pytest.raises(IllegalTransition):
        record.transition("closed", transitions, actor="alice", reason="skip")
    # State unchanged, no history written.
    assert record.state == "draft"
    assert record.history == []


def test_statemachine_can_transition_predicate() -> None:
    record: StatefulRecord[str] = StatefulRecord(state="draft")
    transitions = {"draft": {"active"}, "active": {"closed"}, "closed": set()}
    assert record.can_transition("active", transitions) is True
    assert record.can_transition("closed", transitions) is False


# ---------- alerter --------------------------------------------------------


def test_alerter_higher_is_worse_green_to_red_progression() -> None:
    t = Thresholds(amber=50, red=80, direction="higher_is_worse")
    assert t.classify(10) is AlertLevel.GREEN
    assert t.classify(49) is AlertLevel.GREEN
    assert t.classify(50) is AlertLevel.AMBER
    assert t.classify(79) is AlertLevel.AMBER
    assert t.classify(80) is AlertLevel.RED


def test_alerter_lower_is_worse_inverts() -> None:
    t = Thresholds(amber=0.95, red=0.80, direction="lower_is_worse")
    assert t.classify(0.99) is AlertLevel.GREEN
    assert t.classify(0.95) is AlertLevel.AMBER
    assert t.classify(0.80) is AlertLevel.RED


def test_threshold_alerter_fires_on_transition_only() -> None:
    alerter = ThresholdAlerter(thresholds=Thresholds(amber=10, red=20))
    events: list[AlertLevel] = []

    def on_transition(state):  # type: ignore[no-untyped-def]
        events.append(state.level)

    alerter.observe(5, on_transition)  # GREEN → GREEN, no event
    alerter.observe(15, on_transition)  # GREEN → AMBER, event
    alerter.observe(16, on_transition)  # AMBER → AMBER, no event
    alerter.observe(25, on_transition)  # AMBER → RED, event
    assert events == [AlertLevel.AMBER, AlertLevel.RED]


# ---------- scoring --------------------------------------------------------


def test_weighted_average_normalized_ok() -> None:
    scores = [
        WeightedScore(name="a", weight=0.5, value=1.0),
        WeightedScore(name="b", weight=0.5, value=0.0),
    ]
    assert weighted_average(scores) == pytest.approx(0.5)


def test_weighted_average_rejects_unnormalized() -> None:
    scores = [
        WeightedScore(name="a", weight=0.6, value=1.0),
        WeightedScore(name="b", weight=0.5, value=0.0),
    ]
    with pytest.raises(ScoringError):
        weighted_average(scores)


def test_weighted_average_allows_unnormalized_when_opted_in() -> None:
    scores = [
        WeightedScore(name="a", weight=1.0, value=1.0),
        WeightedScore(name="b", weight=1.0, value=0.5),
    ]
    # Not normalized; explicit opt-in should allow.
    total = weighted_average(scores, require_normalized_weights=False)
    assert total == pytest.approx(1.5)


def test_weighted_average_empty_rejected() -> None:
    with pytest.raises(ScoringError):
        weighted_average([])


def test_fairness_ratio_matches_4_5ths_boundary() -> None:
    # 4/5ths rule: 0.8 means parity with reference.
    assert fairness_ratio(0.80, 1.00) == pytest.approx(0.80)
    # Below 0.8 → adverse impact indicator.
    assert fairness_ratio(0.60, 1.00) < 0.80


def test_fairness_ratio_zero_reference_rejects() -> None:
    with pytest.raises(ScoringError):
        fairness_ratio(0.5, 0.0)


def test_dimension_score_requires_matching_keys() -> None:
    values = {"accuracy": 0.9, "cost": 0.8}
    weights = {"accuracy": 0.6}
    with pytest.raises(ScoringError):
        dimension_score(values, weights)


def test_dimension_score_weighted_average_happy_path() -> None:
    values = {"accuracy": 0.9, "completeness": 0.6}
    weights = {"accuracy": 0.5, "completeness": 0.5}
    assert dimension_score(values, weights) == pytest.approx(0.75)


# ---------- TTL ------------------------------------------------------------


def test_ttl_from_seconds_not_expired_initially() -> None:
    ttl = TTL.from_seconds(10.0)
    assert ttl.is_expired() is False
    assert ttl.remaining() > 9.0


def test_ttl_expired_when_past_deadline() -> None:
    ttl = TTL(expires_at=0.0)  # epoch 0 is long past
    assert ttl.is_expired() is True
    assert ttl.remaining() == 0.0


def test_ttl_refresh_produces_new_deadline() -> None:
    ttl = TTL(expires_at=0.0)
    refreshed = ttl.refresh(5.0)
    assert refreshed.is_expired() is False
    # Original left alone — TTL is immutable-style.
    assert ttl.is_expired() is True


def test_is_stale_detects_old_iso() -> None:
    # An obviously-old timestamp is stale.
    assert is_stale("2000-01-01T00:00:00+00:00", max_age_seconds=60) is True


def test_is_stale_tolerates_missing_tz() -> None:
    # Z suffix + naive -> treated as UTC.
    iso_now = now_iso()
    assert is_stale(iso_now, max_age_seconds=60) is False


def test_is_stale_unparseable_treated_as_stale() -> None:
    assert is_stale("not-a-date", max_age_seconds=60) is True


# ---------- patterns -------------------------------------------------------


def test_load_pattern_catalog_compiles_regex(tmp_path: Path) -> None:
    path = tmp_path / "catalog.yaml"
    path.write_text(
        """
patterns:
  - name: guarantee
    regex: "(?i)\\\\bguaranteed?\\\\b"
    severity: high
    description: Performance guarantee
  - name: never_lose
    regex: "never lose"
    severity: medium
""",
        encoding="utf-8",
    )
    catalog = load_pattern_catalog(path)
    assert len(catalog) == 2
    matches = catalog.scan("We guaranteed returns last year.")
    assert [p.name for p in matches] == ["guarantee"]
    assert catalog.get("guarantee").severity == "high"


def test_load_pattern_catalog_rejects_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("patterns:\n  - name: x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_pattern_catalog(path)


def test_load_pattern_catalog_rejects_non_list(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("patterns: not-a-list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_pattern_catalog(path)
