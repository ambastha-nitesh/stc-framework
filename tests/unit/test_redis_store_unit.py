"""Unit tests for :class:`stc_framework.infrastructure.redis_store.RedisStore`.

Uses ``fakeredis.aioredis`` so no Redis process is required. The full
Protocol contract is also exercised via
``tests/contract/test_keyvalue_store_contract.py`` which runs against
``fakeredis`` automatically in CI.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fakeredis", reason="fakeredis not installed")

import fakeredis.aioredis

from stc_framework.infrastructure.redis_store import RedisStore
from stc_framework.infrastructure.store import StoreError


def _store() -> RedisStore:
    return RedisStore(client=fakeredis.aioredis.FakeRedis(), namespace="stc-test")


@pytest.mark.asyncio
async def test_from_url_requires_tls_when_requested() -> None:
    with pytest.raises(ValueError):
        RedisStore.from_url("redis://localhost:6379/0", require_tls=True)


@pytest.mark.asyncio
async def test_set_get_roundtrip_dict() -> None:
    s = _store()
    await s.set("doc:1", {"tenant": "t-a", "size": 42})
    assert await s.get("doc:1") == {"tenant": "t-a", "size": 42}
    await s.close()


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    s = _store()
    assert await s.get("nope") is None
    await s.close()


@pytest.mark.asyncio
async def test_incr_sets_ttl_only_on_create() -> None:
    s = _store()
    v1 = await s.incr("c", ttl_seconds=100)
    assert v1 == 1
    # Underlying client should now have a positive TTL on the counter.
    ttl_after_create = await s._client.pttl(s._key("c"))  # type: ignore[attr-defined]
    assert ttl_after_create > 0

    v2 = await s.incr("c", ttl_seconds=999)  # would extend if we incorrectly refreshed
    assert v2 == 2
    ttl_after_incr = await s._client.pttl(s._key("c"))  # type: ignore[attr-defined]
    assert ttl_after_incr <= ttl_after_create
    await s.close()


@pytest.mark.asyncio
async def test_keys_uses_scan_and_strips_namespace() -> None:
    s = _store()
    await s.set("risk:t-a:r-1", 1)
    await s.set("risk:t-a:r-2", 2)
    await s.set("other:1", 3)
    matched = await s.keys("risk:t-a:*")
    assert matched == ["risk:t-a:r-1", "risk:t-a:r-2"]
    await s.close()


@pytest.mark.asyncio
async def test_erase_tenant_segment_exact_match() -> None:
    """Regression for v0.3.0 staff-review R1: ``"t"`` must NOT match ``"t1"``."""
    s = _store()
    await s.set("risk:t:r-1", "a")
    await s.set("risk:t1:r-1", "b")
    await s.set("risk:t:t:r-1", "c")  # tenant id appears twice as a segment
    removed = await s.erase_tenant("t", key_prefix="risk:")
    # Both keys where 't' is a segment removed; the 't1' key stays.
    assert removed == 2
    assert await s.get("risk:t:r-1") is None
    assert await s.get("risk:t1:r-1") == "b"
    assert await s.get("risk:t:t:r-1") is None
    await s.close()


@pytest.mark.asyncio
async def test_erase_tenant_empty_id_is_noop() -> None:
    s = _store()
    await s.set("risk::r-1", "a")
    assert await s.erase_tenant("") == 0
    assert await s.get("risk::r-1") == "a"
    await s.close()


@pytest.mark.asyncio
async def test_healthcheck_ok_for_fake_redis() -> None:
    s = _store()
    assert await s.healthcheck() is True
    await s.close()


@pytest.mark.asyncio
async def test_concurrent_incr_atomic() -> None:
    s = _store()
    await asyncio.gather(*[s.incr("counter") for _ in range(40)])
    assert await s.get("counter") == 40
    await s.close()


@pytest.mark.asyncio
async def test_set_with_ttl_expires() -> None:
    s = _store()
    await s.set("tmp", "v", ttl_seconds=0.05)
    assert await s.get("tmp") == "v"
    await asyncio.sleep(0.1)
    assert await s.get("tmp") is None
    await s.close()


@pytest.mark.asyncio
async def test_get_wraps_redis_error_in_store_error() -> None:
    class _Broken:
        async def get(self, _key):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        async def aclose(self):  # type: ignore[no-untyped-def]
            pass

    s = RedisStore(client=_Broken(), namespace="ns")
    with pytest.raises(StoreError):
        await s.get("k")
    await s.close()
