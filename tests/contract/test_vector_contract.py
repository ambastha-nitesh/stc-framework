import pytest

from stc_framework.adapters.vector_store.base import VectorRecord, VectorStore
from stc_framework.adapters.vector_store.in_memory import InMemoryVectorStore


async def _contract(store: VectorStore) -> None:
    await store.ensure_collection("test", 4)
    await store.upsert(
        "test",
        [VectorRecord(id="a", vector=[1, 0, 0, 0], text="alpha")],
    )
    hits = await store.search("test", [1, 0, 0, 0], top_k=1)
    assert hits
    assert await store.healthcheck()


@pytest.mark.asyncio
async def test_in_memory_store_satisfies_contract():
    await _contract(InMemoryVectorStore())
