"""Tests for :mod:`stc_framework.risk.kri`."""

from __future__ import annotations

import pytest

from stc_framework.infrastructure.store import InMemoryStore
from stc_framework.risk.kri import (
    DEFAULT_KRIS,
    KRIDefinition,
    KRIEngine,
    KRIStatus,
)


def test_default_catalog_has_expected_ids() -> None:
    ids = {k.kri_id for k in DEFAULT_KRIS}
    assert "accuracy_rate" in ids
    assert "hallucination_rate" in ids
    assert "sovereignty_violations" in ids
    assert "budget_saturation" in ids


def test_default_kri_thresholds_are_consistent_for_each_direction() -> None:
    for k in DEFAULT_KRIS:
        if k.direction == "higher_is_worse":
            assert k.amber < k.red, f"{k.kri_id}: amber must be < red for higher_is_worse"
        else:
            assert k.amber > k.red, f"{k.kri_id}: amber must be > red for lower_is_worse"


@pytest.mark.asyncio
async def test_record_with_unknown_kri_raises() -> None:
    engine = KRIEngine(store=InMemoryStore())
    with pytest.raises(KeyError):
        await engine.record("does-not-exist", 0.5)


@pytest.mark.asyncio
async def test_register_and_record_green() -> None:
    engine = KRIEngine(store=InMemoryStore())
    await engine.register(KRIDefinition(kri_id="k1", name="k1", direction="higher_is_worse", amber=5, red=10))
    m = await engine.record("k1", 1.0)
    assert m.status is KRIStatus.GREEN


@pytest.mark.asyncio
async def test_amber_threshold_classification() -> None:
    engine = KRIEngine(store=InMemoryStore())
    await engine.register(KRIDefinition(kri_id="k1", name="k1", direction="higher_is_worse", amber=5, red=10))
    m = await engine.record("k1", 5.0)
    assert m.status is KRIStatus.AMBER


@pytest.mark.asyncio
async def test_red_threshold_classification_and_escalation() -> None:
    calls: list[tuple[str, str]] = []

    async def escalate(kri_id: str, risk_id: str) -> None:
        calls.append((kri_id, risk_id))

    engine = KRIEngine(store=InMemoryStore(), escalate_callback=escalate)
    await engine.register(
        KRIDefinition(
            kri_id="k1",
            name="k1",
            direction="higher_is_worse",
            amber=5,
            red=10,
            linked_risks=["r-1", "r-2"],
        )
    )
    m = await engine.record("k1", 20.0)
    assert m.status is KRIStatus.RED
    # Both linked risks escalated.
    assert calls == [("k1", "r-1"), ("k1", "r-2")]


@pytest.mark.asyncio
async def test_latest_returns_most_recent_measurement() -> None:
    engine = KRIEngine(store=InMemoryStore())
    await engine.register(KRIDefinition(kri_id="k1", name="k1", direction="higher_is_worse", amber=5, red=10))
    await engine.record("k1", 3.0)
    await engine.record("k1", 8.0)
    latest = await engine.latest("k1")
    assert latest is not None
    assert latest.value == 8.0
    assert latest.status is KRIStatus.AMBER


@pytest.mark.asyncio
async def test_bootstrap_defaults_registers_full_catalog() -> None:
    engine = KRIEngine(store=InMemoryStore())
    await engine.bootstrap_defaults()
    dash = await engine.dashboard()
    # All default KRIs appear with status=unknown until first measurement.
    assert set(dash.keys()) == {k.kri_id for k in DEFAULT_KRIS}
    for v in dash.values():
        assert v["status"] == "unknown"


@pytest.mark.asyncio
async def test_any_red_lists_red_kris_only() -> None:
    engine = KRIEngine(store=InMemoryStore())
    await engine.register(KRIDefinition(kri_id="k_green", name="g", direction="higher_is_worse", amber=5, red=10))
    await engine.register(KRIDefinition(kri_id="k_red", name="r", direction="higher_is_worse", amber=5, red=10))
    await engine.record("k_green", 1.0)
    await engine.record("k_red", 50.0)
    red = await engine.any_red()
    assert red == ["k_red"]
