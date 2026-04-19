"""Tests for :mod:`stc_framework.infrastructure.session_state`."""

from __future__ import annotations

import asyncio

import pytest

from stc_framework.errors import SessionExpired
from stc_framework.infrastructure.session_state import (
    SessionManager,
    usd_from_micro,
    usd_to_micro,
)
from stc_framework.infrastructure.store import InMemoryStore


def test_usd_roundtrip() -> None:
    assert usd_to_micro(1.234567) == 1_234_567
    assert usd_from_micro(1_234_567) == pytest.approx(1.234567)


@pytest.mark.asyncio
async def test_create_and_get_metadata() -> None:
    mgr = SessionManager(InMemoryStore())
    meta = await mgr.create_session("s-1", tenant_id="t-a", data_tier="internal")
    assert meta.session_id == "s-1"
    fetched = await mgr.get_metadata("s-1")
    assert fetched is not None
    assert fetched.tenant_id == "t-a"


@pytest.mark.asyncio
async def test_assert_active_raises_for_missing_session() -> None:
    mgr = SessionManager(InMemoryStore())
    with pytest.raises(SessionExpired):
        await mgr.assert_active("never-existed")


@pytest.mark.asyncio
async def test_save_and_load_context() -> None:
    mgr = SessionManager(InMemoryStore())
    await mgr.create_session("s-1")
    await mgr.save_context("s-1", {"turns": [{"role": "user", "text": "hi"}]})
    ctx = await mgr.load_context("s-1")
    assert ctx is not None
    assert ctx["turns"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_save_and_load_token_map_blob() -> None:
    mgr = SessionManager(InMemoryStore())
    await mgr.create_session("s-1")
    await mgr.save_token_map("s-1", "blob-base64")
    assert await mgr.load_token_map("s-1") == "blob-base64"


@pytest.mark.asyncio
async def test_destroy_clears_all_keys() -> None:
    mgr = SessionManager(InMemoryStore())
    await mgr.create_session("s-1")
    await mgr.save_context("s-1", {"x": 1})
    await mgr.save_token_map("s-1", "blob")
    await mgr.destroy_session("s-1")
    assert await mgr.get_metadata("s-1") is None


@pytest.mark.asyncio
async def test_session_ttl_expires() -> None:
    mgr = SessionManager(InMemoryStore(), default_ttl_seconds=1)
    await mgr.create_session("s-1", ttl_seconds=0.05)  # type: ignore[arg-type]
    await asyncio.sleep(0.1)
    with pytest.raises(SessionExpired):
        await mgr.assert_active("s-1")


@pytest.mark.asyncio
async def test_cost_accumulator_atomic() -> None:
    mgr = SessionManager(InMemoryStore())
    total_a = await mgr.increment_cost("stalwart", usd=0.10)
    total_b = await mgr.increment_cost("stalwart", usd=0.05)
    assert total_a == pytest.approx(0.10)
    assert total_b == pytest.approx(0.15)


@pytest.mark.asyncio
async def test_cost_concurrent_increments_are_consistent() -> None:
    mgr = SessionManager(InMemoryStore())

    async def bump() -> None:
        await mgr.increment_cost("stalwart", usd=0.01)

    await asyncio.gather(*[bump() for _ in range(30)])
    # Read via the counter key.
    store = mgr._store  # type: ignore[attr-defined]
    from stc_framework.infrastructure.session_state import _today_utc  # type: ignore[attr-defined]

    raw = await store.get(f"cost:{_today_utc()}:stalwart")
    assert usd_from_micro(int(raw)) == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_rate_limit_counter() -> None:
    mgr = SessionManager(InMemoryStore())
    assert await mgr.check_rate_limit("stalwart", per_minute_cap=100) == 1
    assert await mgr.check_rate_limit("stalwart", per_minute_cap=100) == 2


@pytest.mark.asyncio
async def test_health_reflects_store() -> None:
    mgr = SessionManager(InMemoryStore())
    assert await mgr.health() is True
