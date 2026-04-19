"""Tests for :mod:`stc_framework.governance.catalog`."""

from __future__ import annotations

import asyncio

import pytest

from stc_framework.governance.catalog import (
    QUALITY_WEIGHTS,
    AssetStatus,
    DataCatalog,
    ModelStatus,
    QualityDimensions,
)
from stc_framework.infrastructure.store import InMemoryStore


def test_quality_weights_sum_to_one() -> None:
    assert round(sum(QUALITY_WEIGHTS.values()), 6) == 1.0


def test_quality_composite_all_ones_is_one() -> None:
    q = QualityDimensions()
    assert q.composite == pytest.approx(1.0)


def test_quality_composite_all_zeros_is_zero() -> None:
    q = QualityDimensions(
        accuracy=0.0,
        completeness=0.0,
        timeliness=0.0,
        consistency=0.0,
        uniqueness=0.0,
        validity=0.0,
    )
    assert q.composite == pytest.approx(0.0)


def test_quality_accuracy_dominates() -> None:
    # With accuracy at its weight (0.35), any single dimension change is
    # reflected proportionally. We check monotonicity: lowering accuracy
    # alone should reduce composite more than lowering consistency alone.
    baseline = QualityDimensions().composite
    drop_accuracy = QualityDimensions(accuracy=0.0).composite
    drop_consistency = QualityDimensions(consistency=0.0).composite
    assert drop_accuracy < drop_consistency < baseline


@pytest.mark.asyncio
async def test_register_and_get_document() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store)
    asset = await catalog.register_document("doc-1", metadata={"source": "10-K"})
    assert asset.asset_id == "doc-1"
    assert asset.status is AssetStatus.ACTIVE
    fetched = await catalog.get_document("doc-1")
    assert fetched is not None
    assert fetched.metadata == {"source": "10-K"}


@pytest.mark.asyncio
async def test_update_quality_below_threshold_quarantines() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store, quarantine_threshold=0.6)
    await catalog.register_document("doc-1")
    bad = QualityDimensions(
        accuracy=0.1,
        completeness=0.1,
        timeliness=0.1,
        consistency=0.1,
        uniqueness=0.1,
        validity=0.1,
    )
    updated = await catalog.update_quality("doc-1", bad)
    assert updated.status is AssetStatus.QUARANTINED


@pytest.mark.asyncio
async def test_update_quality_above_threshold_stays_active() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store, quarantine_threshold=0.5)
    await catalog.register_document("doc-1")
    good = QualityDimensions(
        accuracy=0.9,
        completeness=0.9,
        timeliness=0.9,
        consistency=0.9,
        uniqueness=0.9,
        validity=0.9,
    )
    updated = await catalog.update_quality("doc-1", good)
    assert updated.status is AssetStatus.ACTIVE


@pytest.mark.asyncio
async def test_update_quality_on_missing_doc_raises() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store)
    with pytest.raises(KeyError):
        await catalog.update_quality("missing", QualityDimensions())


@pytest.mark.asyncio
async def test_deprecate_document_transitions_status() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store)
    await catalog.register_document("doc-1")
    updated = await catalog.deprecate_document("doc-1", reason="superseded")
    assert updated.status is AssetStatus.DEPRECATED


@pytest.mark.asyncio
async def test_sweep_freshness_marks_stale_past_sla() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store)
    # SLA of 0.01s so we can expire it deliberately.
    await catalog.register_document("doc-1", freshness_sla_seconds=0.01)
    await asyncio.sleep(0.05)
    transitioned = await catalog.sweep_freshness()
    assert transitioned == 1
    after = await catalog.get_document("doc-1")
    assert after is not None
    assert after.status is AssetStatus.STALE
    # Second sweep is a no-op — already stale.
    assert await catalog.sweep_freshness() == 0


@pytest.mark.asyncio
async def test_model_lifecycle_transitions() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store)
    model = await catalog.register_model("gpt-4")
    assert model.status is ModelStatus.EVALUATION
    approved = await catalog.transition_model("gpt-4", ModelStatus.APPROVED)
    assert approved.status is ModelStatus.APPROVED
    deployed = await catalog.transition_model("gpt-4", ModelStatus.DEPLOYED)
    assert deployed.status is ModelStatus.DEPLOYED


@pytest.mark.asyncio
async def test_prompt_register_and_set_active_flips_flag() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store)
    await catalog.register_prompt("p1", "v1")
    await catalog.register_prompt("p1", "v2")
    await catalog.set_active_prompt("p1", "v2")
    # Read the two prompts back and verify exactly one is active.
    keys = await store.keys("catalog:prompt:p1:*")
    actives = [(await store.get(k)).get("active") for k in keys]
    assert actives.count(True) == 1
    # And the active one is v2 specifically.
    for k in keys:
        raw = await store.get(k)
        if raw and raw["version"] == "v2":
            assert raw["active"] is True


@pytest.mark.asyncio
async def test_governance_scorecard_counts_and_avg() -> None:
    store = InMemoryStore()
    catalog = DataCatalog(store=store, quarantine_threshold=0.0)
    await catalog.register_document("d1")
    await catalog.register_document("d2")
    await catalog.register_model("m1")
    report = await catalog.governance_scorecard()
    assert report["documents_by_status"][AssetStatus.ACTIVE.value] == 2
    assert report["models_by_status"][ModelStatus.EVALUATION.value] == 1
    assert report["avg_document_quality"] == pytest.approx(1.0)
    assert report["asset_counts"]["documents"] == 2
