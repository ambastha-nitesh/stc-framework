import pytest

from stc_framework.adapters.vector_store.base import VectorRecord
from stc_framework.adapters.vector_store.in_memory import InMemoryVectorStore
from stc_framework.errors import CollectionMissing


@pytest.mark.asyncio
async def test_upsert_and_search_returns_top_k():
    store = InMemoryVectorStore()
    await store.ensure_collection("c", 4)
    await store.upsert(
        "c",
        [
            VectorRecord(id="a", vector=[1, 0, 0, 0], text="alpha"),
            VectorRecord(id="b", vector=[0, 1, 0, 0], text="beta"),
            VectorRecord(id="c", vector=[1, 0, 0, 0], text="alpha-ish"),
        ],
    )
    results = await store.search("c", [1, 0, 0, 0], top_k=2)
    assert {r.id for r in results} == {"a", "c"}


@pytest.mark.asyncio
async def test_search_missing_collection_raises():
    store = InMemoryVectorStore()
    with pytest.raises(CollectionMissing):
        await store.search("nope", [1, 0, 0, 0])


@pytest.mark.asyncio
async def test_keyword_search_returns_overlapping_docs():
    store = InMemoryVectorStore()
    await store.ensure_collection("c", 4)
    await store.upsert(
        "c",
        [
            VectorRecord(id="a", vector=[1, 0, 0, 0], text="revenue was strong"),
            VectorRecord(id="b", vector=[0, 1, 0, 0], text="weather outlook"),
        ],
    )
    results = await store.keyword_search("c", "revenue")
    assert results[0].id == "a"


@pytest.mark.asyncio
async def test_upsert_idempotent():
    store = InMemoryVectorStore()
    await store.ensure_collection("c", 4)
    rec = VectorRecord(id="x", vector=[1, 0, 0, 0], text="hello")
    await store.upsert("c", [rec])
    await store.upsert("c", [rec])
    results = await store.search("c", [1, 0, 0, 0], top_k=5)
    assert len(results) == 1
