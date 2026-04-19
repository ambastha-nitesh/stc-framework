"""Tests for :mod:`stc_framework.governance.lineage`."""

from __future__ import annotations

import pytest

from stc_framework.governance.lineage import (
    ContextAssemblyNode,
    EmbeddingNode,
    GenerationNode,
    LineageBuilder,
    LineageStore,
    ResponseNode,
    RetrievalNode,
    SourceDocumentNode,
    ValidationNode,
)
from stc_framework.infrastructure.store import InMemoryStore


def _build_full_record(lineage_id: str = "trace-1", *, session_id: str | None = None):
    return (
        LineageBuilder(lineage_id, tenant_id="t-a", session_id=session_id)
        .add_source_documents(
            [
                SourceDocumentNode(doc_id="d-1", collection="c"),
                SourceDocumentNode(doc_id="d-2", collection="c"),
            ]
        )
        .add_embedding(EmbeddingNode(embedder_id="bge", vector_size=768))
        .add_retrieval(RetrievalNode(collection="c", top_k=3, doc_ids=["d-1", "d-2"]))
        .add_context_assembly(ContextAssemblyNode(chunk_count=4, total_chars=2048))
        .add_generation(GenerationNode(model_id="gpt-4", input_tokens=100, output_tokens=40))
        .add_validation(ValidationNode(rails=[{"name": "pii"}], action="pass"))
        .add_response(ResponseNode(status="delivered", char_count=200))
        .build()
    )


def test_builder_seals_record_on_build() -> None:
    record = _build_full_record()
    assert record.sealed is True
    assert record.sealed_at is not None
    assert record.generation is not None
    assert record.generation.model_id == "gpt-4"


def test_builder_chained_calls_return_self() -> None:
    builder = LineageBuilder("trace-chain")
    returned = builder.add_embedding(EmbeddingNode(embedder_id="e", vector_size=128))
    assert returned is builder


@pytest.mark.asyncio
async def test_store_refuses_unsealed_record() -> None:
    store = InMemoryStore()
    lineage = LineageStore(store=store)
    builder = LineageBuilder("trace-unsealed")
    # Deliberately don't call .build() — lineage is unsealed.
    with pytest.raises(ValueError):
        await lineage.store(builder._record)  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_store_and_retrieve_record_roundtrip() -> None:
    store = InMemoryStore()
    lineage = LineageStore(store=store)
    record = _build_full_record(lineage_id="trace-rt", session_id="s-1")
    await lineage.store(record)
    fetched = await lineage.get("trace-rt")
    assert fetched is not None
    assert fetched.lineage_id == "trace-rt"
    assert fetched.session_id == "s-1"
    assert fetched.generation is not None
    assert fetched.generation.model_id == "gpt-4"


@pytest.mark.asyncio
async def test_by_document_index_populated() -> None:
    store = InMemoryStore()
    lineage = LineageStore(store=store)
    await lineage.store(_build_full_record("trace-1"))
    await lineage.store(_build_full_record("trace-2"))
    docs_for_d1 = await lineage.by_document("d-1")
    assert set(docs_for_d1) == {"trace-1", "trace-2"}


@pytest.mark.asyncio
async def test_by_model_and_session_indexes() -> None:
    store = InMemoryStore()
    lineage = LineageStore(store=store)
    await lineage.store(_build_full_record("trace-1", session_id="s-1"))
    await lineage.store(_build_full_record("trace-2", session_id="s-1"))
    by_model = await lineage.by_model("gpt-4")
    assert set(by_model) == {"trace-1", "trace-2"}
    by_session = await lineage.by_session("s-1")
    assert set(by_session) == {"trace-1", "trace-2"}


@pytest.mark.asyncio
async def test_impact_analysis_returns_affected_responses() -> None:
    store = InMemoryStore()
    lineage = LineageStore(store=store)
    await lineage.store(_build_full_record("trace-1"))
    await lineage.store(_build_full_record("trace-2"))
    result = await lineage.impact_analysis("d-1")
    assert result["lineage_count"] == 2
    assert set(result["affected_lineage_ids"]) == {"trace-1", "trace-2"}
    assert result["by_model"]["gpt-4"] == 2


@pytest.mark.asyncio
async def test_coverage_report_distinct_counts() -> None:
    store = InMemoryStore()
    lineage = LineageStore(store=store)
    await lineage.store(_build_full_record("trace-1"))
    await lineage.store(_build_full_record("trace-2"))
    report = await lineage.coverage_report()
    assert report["total_records"] == 2
    assert report["distinct_models"] == 1
    assert report["distinct_tenants"] == 1
