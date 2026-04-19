"""Enterprise-risk regression tests.

Covers:
- per-tenant budget enforcement
- idempotency key replay
- graceful shutdown drain
- startup fail-fast
- adapter healthcheck gauges
- in-flight request counter
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from stc_framework.adapters.embeddings.hash_embedder import HashEmbedder
from stc_framework.adapters.llm.mock import MockLLMClient
from stc_framework.adapters.vector_store.base import VectorRecord
from stc_framework.adapters.vector_store.in_memory import InMemoryVectorStore
from stc_framework.config.settings import STCSettings
from stc_framework.errors import STCError
from stc_framework.governance.budget import (
    TenantBudgetExceeded,
    TenantBudgetTracker,
)
from stc_framework.governance.idempotency import IdempotencyCache
from stc_framework.system import STCSystem


def _make_system(tmp_path: Path, fixture_dir: Path) -> STCSystem:
    settings = STCSettings(
        presidio_enabled=False,
        metrics_enabled=False,
        log_format="text",
        audit_path=str(tmp_path / "audit"),
    )
    return STCSystem.from_spec(
        fixture_dir / "minimal_spec.yaml",
        settings=settings,
        llm=MockLLMClient(),
        vector_store=InMemoryVectorStore(),
        embeddings=HashEmbedder(vector_size=64),
    )


async def _seed(system: STCSystem, tenant: str = "t1") -> None:
    emb = system.embeddings
    vec = (
        await emb.aembed_batch(
            ["Revenue was $24,050 million. [Document: acme, Page 1]"]
        )
    )[0]
    await system.vector_store.ensure_collection("financial_docs", emb.vector_size)
    await system.vector_store.upsert(
        "financial_docs",
        [
            VectorRecord(
                id=f"seed-{tenant}",
                vector=vec,
                text="Revenue was $24,050 million. [Document: acme, Page 1]",
                metadata={"source": "acme", "page": 1, "tenant_id": tenant},
            )
        ],
    )


# ---------------------------------------------------------------------------
# E1 — Per-tenant budget enforcement
# ---------------------------------------------------------------------------


class TestBudgetTracker:
    def test_records_and_sums_cost(self):
        tracker = TenantBudgetTracker(daily_usd=10.0)
        tracker.record_cost("acme", 1.0)
        tracker.record_cost("acme", 2.5)
        assert tracker.observed("acme", window="daily") == pytest.approx(3.5)

    def test_enforce_raises_when_over_limit(self):
        tracker = TenantBudgetTracker(daily_usd=5.0)
        tracker.record_cost("acme", 6.0)
        with pytest.raises(TenantBudgetExceeded) as exc:
            tracker.enforce("acme")
        assert exc.value.window == "daily"
        assert exc.value.observed >= 5.0

    def test_tenants_are_isolated(self):
        tracker = TenantBudgetTracker(daily_usd=5.0)
        tracker.record_cost("acme", 10.0)
        # bob under budget
        tracker.enforce("bob")  # does not raise

    def test_erase_tenant_drops_samples(self):
        # Samples on the same UTC day aggregate into a single bucket in
        # the rolling-window implementation, so erase_tenant reports the
        # bucket count (== 1 here). The important invariant is that
        # observed drops to zero.
        tracker = TenantBudgetTracker(daily_usd=5.0)
        tracker.record_cost("acme", 1.0)
        tracker.record_cost("acme", 2.0)
        removed = tracker.erase_tenant("acme")
        assert removed >= 1
        assert tracker.observed("acme", window="daily") == 0.0


class TestBudgetSystemIntegration:
    @pytest.mark.asyncio
    async def test_tenant_over_budget_is_rejected(
        self, tmp_path: Path, fixture_dir: Path, monkeypatch
    ):
        system = _make_system(tmp_path, fixture_dir)
        await _seed(system, tenant="poor")
        # Force the tenant over their daily budget.
        system._budget.daily_usd = 0.01
        system._budget.record_cost("poor", 1.0)
        try:
            with pytest.raises(STCError) as exc:
                await system.aquery("q", tenant_id="poor")
            assert "budget" in str(exc.value).lower()
        finally:
            await system.astop()


# ---------------------------------------------------------------------------
# E2 — Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_cache_roundtrip(self):
        cache = IdempotencyCache(max_entries=10, ttl_seconds=60)
        cache.put("t1", "key1", {"x": 1})
        assert cache.get("t1", "key1") == {"x": 1}

    def test_cache_scoped_per_tenant(self):
        cache = IdempotencyCache(max_entries=10, ttl_seconds=60)
        cache.put("t1", "key1", "t1-result")
        assert cache.get("t2", "key1") is None

    def test_cache_expires(self):
        cache = IdempotencyCache(max_entries=10, ttl_seconds=0)
        cache.put("t1", "key1", "x")
        assert cache.get("t1", "key1") is None

    def test_cache_evicts_over_capacity(self):
        cache = IdempotencyCache(max_entries=2, ttl_seconds=60)
        cache.put("t1", "k1", 1)
        cache.put("t1", "k2", 2)
        cache.put("t1", "k3", 3)
        assert cache.get("t1", "k1") is None
        assert len(cache) == 2

    def test_empty_key_disables_cache(self):
        cache = IdempotencyCache()
        cache.put("t1", "", "x")
        assert cache.get("t1", "") is None

    @pytest.mark.asyncio
    async def test_system_idempotent_replay_returns_cached_result(
        self, tmp_path: Path, fixture_dir: Path
    ):
        system = _make_system(tmp_path, fixture_dir)
        await _seed(system, tenant="t")
        try:
            r1 = await system.aquery("q", tenant_id="t", idempotency_key="k-1")
            r2 = await system.aquery("q", tenant_id="t", idempotency_key="k-1")
            assert r1.trace_id == r2.trace_id
            # Only ONE trace should have been recorded in stats.
            assert system._stats.total_queries == 1
        finally:
            await system.astop()


# ---------------------------------------------------------------------------
# E3 — Graceful shutdown
# ---------------------------------------------------------------------------


class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_astop_drains_inflight_before_closing(
        self, tmp_path: Path, fixture_dir: Path
    ):
        system = _make_system(tmp_path, fixture_dir)
        await _seed(system)
        try:
            # Run a query — inflight should rise then fall.
            await system.aquery("q", tenant_id="t1")
            assert system._inflight.current == 0
            drained = await system.astop(drain_timeout=5.0)
            assert drained is True
        finally:
            # astop called twice is harmless.
            pass

    @pytest.mark.asyncio
    async def test_stopping_flag_rejects_new_requests(
        self, tmp_path: Path, fixture_dir: Path
    ):
        system = _make_system(tmp_path, fixture_dir)
        system._stopping = True
        with pytest.raises(STCError):
            await system.aquery("q")


# ---------------------------------------------------------------------------
# E4 — Startup fail-fast
# ---------------------------------------------------------------------------


class TestStartupFailFast:
    @pytest.mark.asyncio
    async def test_strict_health_raises_when_adapter_down(
        self, tmp_path: Path, fixture_dir: Path
    ):
        system = _make_system(tmp_path, fixture_dir)

        async def broken():
            raise RuntimeError("cannot reach LLM provider")

        system._llm.healthcheck = broken  # type: ignore[assignment]

        with pytest.raises(STCError) as exc:
            await system.astart(strict_health=True, health_timeout=1.0)
        assert "startup health" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_non_strict_mode_tolerates_unhealthy_adapter(
        self, tmp_path: Path, fixture_dir: Path
    ):
        system = _make_system(tmp_path, fixture_dir)

        async def broken():
            return False

        system._llm.healthcheck = broken  # type: ignore[assignment]
        try:
            await system.astart(strict_health=False, health_timeout=1.0)
            # System starts and accepts queries, but readiness reports
            # the failure.
            report = await system.ahealth_probe()
            assert report.ok is False
        finally:
            await system.astop()
