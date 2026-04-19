"""Contract tests for :class:`~stc_framework.infrastructure.store.KeyValueStore`.

Runs the same suite against every implementation so we catch contract
drift. The in-memory default always runs; backends behind optional
extras (Redis) register themselves via the ``stores`` fixture.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from stc_framework.infrastructure.store import InMemoryStore, KeyValueStore

StoreFactory = Callable[[], KeyValueStore]


def _in_memory() -> KeyValueStore:
    return InMemoryStore()


def _fake_redis() -> KeyValueStore:
    # Skip the factory if fakeredis / the RedisStore are not importable
    # (e.g. an image built without the ``redis`` extra). The
    # importorskip happens at collection via pytest.param marks below.
    import fakeredis.aioredis

    from stc_framework.infrastructure.redis_store import RedisStore

    return RedisStore(
        client=fakeredis.aioredis.FakeRedis(),
        namespace=f"stc-contract-{id(object())}",
    )


_factories: list = [
    pytest.param(_in_memory, id="in_memory"),
    pytest.param(
        _fake_redis,
        id="fake_redis",
        marks=pytest.mark.skipif(
            __import__("importlib").util.find_spec("fakeredis") is None,
            reason="fakeredis not installed",
        ),
    ),
]


@pytest.fixture(params=_factories)
def make_store(request: pytest.FixtureRequest) -> StoreFactory:
    return request.param


@pytest.mark.asyncio
async def test_set_and_get_roundtrip(make_store: StoreFactory) -> None:
    store = make_store()
    await store.set("k1", "hello")
    assert await store.get("k1") == "hello"
    await store.close()


@pytest.mark.asyncio
async def test_missing_key_returns_none(make_store: StoreFactory) -> None:
    store = make_store()
    assert await store.get("missing") is None
    await store.close()


@pytest.mark.asyncio
async def test_delete_removes_key(make_store: StoreFactory) -> None:
    store = make_store()
    await store.set("k", "v")
    assert await store.delete("k") is True
    assert await store.get("k") is None
    # Deleting a missing key is a no-op returning False.
    assert await store.delete("k") is False
    await store.close()


@pytest.mark.asyncio
async def test_exists_reflects_state(make_store: StoreFactory) -> None:
    store = make_store()
    assert await store.exists("k") is False
    await store.set("k", 1)
    assert await store.exists("k") is True
    await store.delete("k")
    assert await store.exists("k") is False
    await store.close()


@pytest.mark.asyncio
async def test_incr_from_zero_and_existing(make_store: StoreFactory) -> None:
    store = make_store()
    assert await store.incr("counter") == 1
    assert await store.incr("counter", amount=4) == 5
    assert await store.incr("counter", amount=-2) == 3
    await store.close()


@pytest.mark.asyncio
async def test_ttl_expiry(make_store: StoreFactory) -> None:
    store = make_store()
    await store.set("tmp", "v", ttl_seconds=0.05)
    assert await store.get("tmp") == "v"
    await asyncio.sleep(0.1)
    assert await store.get("tmp") is None
    await store.close()


@pytest.mark.asyncio
async def test_keys_pattern_match(make_store: StoreFactory) -> None:
    store = make_store()
    await store.set("risk:t1:r1", {"id": "r1"})
    await store.set("risk:t1:r2", {"id": "r2"})
    await store.set("other:t1:foo", {"id": "foo"})
    matched = await store.keys("risk:t1:*")
    assert sorted(matched) == ["risk:t1:r1", "risk:t1:r2"]
    await store.close()


@pytest.mark.asyncio
async def test_erase_tenant_removes_only_that_tenant(make_store: StoreFactory) -> None:
    store = make_store()
    await store.set("risk:tenant-a:r1", "x")
    await store.set("risk:tenant-a:r2", "y")
    await store.set("risk:tenant-b:r1", "z")
    removed = await store.erase_tenant("tenant-a", key_prefix="risk:")
    assert removed == 2
    assert await store.get("risk:tenant-a:r1") is None
    assert await store.get("risk:tenant-b:r1") == "z"
    await store.close()


@pytest.mark.asyncio
async def test_healthcheck_ok_for_default(make_store: StoreFactory) -> None:
    store = make_store()
    assert await store.healthcheck() is True
    await store.close()


@pytest.mark.asyncio
async def test_concurrent_incr_is_atomic(make_store: StoreFactory) -> None:
    store = make_store()
    await asyncio.gather(*[store.incr("c") for _ in range(50)])
    assert await store.get("c") == 50
    await store.close()
