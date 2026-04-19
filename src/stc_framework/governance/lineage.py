"""End-to-end data lineage.

Every STC request produces a connected graph:

    source documents -> embedding -> retrieval ->
    context assembly -> LLM generation -> critic validation -> response

Storing that graph per-request lets auditors (and regulators, e.g.
EU AI Act Art. 12, FINRA 3110, BCBS 239) trace any response back to
the inputs, models, and rails that produced it.

``lineage_id`` is deliberately identical to the OpenTelemetry trace id
so traces and lineage records join with a single hop. The record is
built incrementally by the pipeline (stage by stage via
:class:`LineageBuilder`) and sealed once the response is emitted.

State lives in a :class:`~stc_framework.infrastructure.store.KeyValueStore`,
so multi-process deployments share a single lineage history.

Secondary indexes support three common auditor queries:

* ``by_document(doc_id)`` — every response that used a specific document.
* ``by_model(model_id)`` — every response that used a specific model.
* ``by_session(session_id)`` — every response in a conversation.

And a bulk ``impact_analysis(doc_id)`` operation answers: "if I remove
this document, which past responses are affected?" — crucial for DSAR
erasure and recall scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from stc_framework.governance.events import AuditEvent
from stc_framework.infrastructure.store import KeyValueStore
from stc_framework.observability.audit import AuditLogger, AuditRecord


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- node types -----------------------------------------------------------


@dataclass
class SourceDocumentNode:
    doc_id: str
    collection: str = ""
    hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EmbeddingNode:
    embedder_id: str
    vector_size: int
    duration_ms: float | None = None


@dataclass
class RetrievalNode:
    collection: str
    top_k: int
    doc_ids: list[str] = field(default_factory=list)
    duration_ms: float | None = None


@dataclass
class ContextAssemblyNode:
    chunk_count: int
    total_chars: int
    strategy: str = "concat"


@dataclass
class GenerationNode:
    model_id: str
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: float | None = None
    cost_usd: float | None = None


@dataclass
class ValidationNode:
    rails: list[dict[str, Any]] = field(default_factory=list)
    action: str = "pass"
    escalation_level: str | None = None


@dataclass
class ResponseNode:
    status: str = "delivered"
    char_count: int = 0


# ---- record + builder -----------------------------------------------------


@dataclass
class LineageRecord:
    """A fully-built lineage graph for one request.

    All fields are optional until the pipeline stage populates them.
    ``sealed`` flips to True once :meth:`LineageBuilder.build` runs; a
    sealed record is safe to persist.
    """

    lineage_id: str
    tenant_id: str | None = None
    session_id: str | None = None
    started_at: str = field(default_factory=_utc_now)
    sealed_at: str | None = None
    sealed: bool = False

    sources: list[SourceDocumentNode] = field(default_factory=list)
    embedding: EmbeddingNode | None = None
    retrieval: RetrievalNode | None = None
    context: ContextAssemblyNode | None = None
    generation: GenerationNode | None = None
    validation: ValidationNode | None = None
    response: ResponseNode | None = None


class LineageBuilder:
    """Incremental builder — a single builder follows one request.

    Each ``add_*`` method returns ``self`` so calls chain where the
    caller wants; most pipelines just call them imperatively. Every
    setter is idempotent (overwrites the previous value for its stage)
    so pipelines that retry a stage don't produce duplicate nodes.
    """

    def __init__(
        self,
        lineage_id: str,
        *,
        tenant_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self._record = LineageRecord(
            lineage_id=lineage_id,
            tenant_id=tenant_id,
            session_id=session_id,
        )

    def add_source_documents(self, docs: list[SourceDocumentNode]) -> LineageBuilder:
        self._record.sources = list(docs)
        return self

    def add_embedding(self, node: EmbeddingNode) -> LineageBuilder:
        self._record.embedding = node
        return self

    def add_retrieval(self, node: RetrievalNode) -> LineageBuilder:
        self._record.retrieval = node
        return self

    def add_context_assembly(self, node: ContextAssemblyNode) -> LineageBuilder:
        self._record.context = node
        return self

    def add_generation(self, node: GenerationNode) -> LineageBuilder:
        self._record.generation = node
        return self

    def add_validation(self, node: ValidationNode) -> LineageBuilder:
        self._record.validation = node
        return self

    def add_response(self, node: ResponseNode) -> LineageBuilder:
        self._record.response = node
        return self

    def build(self) -> LineageRecord:
        self._record.sealed = True
        self._record.sealed_at = _utc_now()
        return self._record


# ---- store ----------------------------------------------------------------


_KEY_LINEAGE = "lineage:record:{lineage_id}"
_KEY_IDX_DOC = "lineage:idx:doc:{doc_id}"
_KEY_IDX_MODEL = "lineage:idx:model:{model_id}"
_KEY_IDX_SESSION = "lineage:idx:session:{session_id}"


class LineageStore:
    """Persistence + index layer for :class:`LineageRecord`."""

    def __init__(self, store: KeyValueStore, *, audit: AuditLogger | None = None) -> None:
        self._store = store
        self._audit = audit

    async def store(self, record: LineageRecord) -> None:
        if not record.sealed:
            raise ValueError("cannot persist unsealed lineage record")
        payload = _record_to_dict(record)
        await self._store.set(_KEY_LINEAGE.format(lineage_id=record.lineage_id), payload)
        # Update secondary indexes. Each index stores a list of lineage ids.
        if record.sources:
            for src in record.sources:
                await self._append_index(_KEY_IDX_DOC.format(doc_id=src.doc_id), record.lineage_id)
        if record.generation is not None:
            await self._append_index(
                _KEY_IDX_MODEL.format(model_id=record.generation.model_id),
                record.lineage_id,
            )
        if record.session_id:
            await self._append_index(
                _KEY_IDX_SESSION.format(session_id=record.session_id),
                record.lineage_id,
            )
        if self._audit is not None:
            await self._audit.emit(
                AuditRecord(
                    timestamp=_utc_now(),
                    trace_id=record.lineage_id,
                    tenant_id=record.tenant_id,
                    event_type=AuditEvent.LINEAGE_RECORDED.value,
                    persona="governance",
                    extra={
                        "lineage_id": record.lineage_id,
                        "source_count": len(record.sources),
                        "model_id": record.generation.model_id if record.generation else None,
                    },
                )
            )

    async def get(self, lineage_id: str) -> LineageRecord | None:
        raw = await self._store.get(_KEY_LINEAGE.format(lineage_id=lineage_id))
        return _record_from_dict(raw) if raw else None

    async def by_document(self, doc_id: str) -> list[str]:
        return list(await self._store.get(_KEY_IDX_DOC.format(doc_id=doc_id)) or [])

    async def by_model(self, model_id: str) -> list[str]:
        return list(await self._store.get(_KEY_IDX_MODEL.format(model_id=model_id)) or [])

    async def by_session(self, session_id: str) -> list[str]:
        return list(await self._store.get(_KEY_IDX_SESSION.format(session_id=session_id)) or [])

    async def impact_analysis(self, doc_id: str) -> dict[str, Any]:
        """Return affected lineage ids plus a summary count by model."""
        lineage_ids = await self.by_document(doc_id)
        by_model: dict[str, int] = {}
        for lid in lineage_ids:
            rec = await self.get(lid)
            if rec and rec.generation is not None:
                by_model[rec.generation.model_id] = by_model.get(rec.generation.model_id, 0) + 1
        return {
            "doc_id": doc_id,
            "lineage_count": len(lineage_ids),
            "affected_lineage_ids": lineage_ids,
            "by_model": by_model,
        }

    async def coverage_report(self) -> dict[str, Any]:
        """High-level snapshot of lineage coverage for dashboards."""
        keys = await self._store.keys("lineage:record:*")
        models: set[str] = set()
        tenants: set[str] = set()
        for k in keys:
            raw = await self._store.get(k)
            if not raw:
                continue
            rec = _record_from_dict(raw)
            if rec.generation is not None:
                models.add(rec.generation.model_id)
            if rec.tenant_id:
                tenants.add(rec.tenant_id)
        return {
            "total_records": len(keys),
            "distinct_models": len(models),
            "distinct_tenants": len(tenants),
        }

    async def _append_index(self, key: str, lineage_id: str) -> None:
        existing = await self._store.get(key) or []
        if isinstance(existing, list):
            if lineage_id not in existing:
                existing.append(lineage_id)
            await self._store.set(key, existing)
        else:
            await self._store.set(key, [lineage_id])


# ---- (de)serialisation ----------------------------------------------------


def _record_to_dict(record: LineageRecord) -> dict[str, Any]:
    def dc(o: Any) -> Any:
        if o is None:
            return None
        return {k: v for k, v in vars(o).items()}

    return {
        "lineage_id": record.lineage_id,
        "tenant_id": record.tenant_id,
        "session_id": record.session_id,
        "started_at": record.started_at,
        "sealed_at": record.sealed_at,
        "sealed": record.sealed,
        "sources": [dc(s) for s in record.sources],
        "embedding": dc(record.embedding),
        "retrieval": dc(record.retrieval),
        "context": dc(record.context),
        "generation": dc(record.generation),
        "validation": dc(record.validation),
        "response": dc(record.response),
    }


def _record_from_dict(raw: dict[str, Any]) -> LineageRecord:
    def as_node(cls: Any, d: Any) -> Any:
        return cls(**d) if isinstance(d, dict) else None

    return LineageRecord(
        lineage_id=raw["lineage_id"],
        tenant_id=raw.get("tenant_id"),
        session_id=raw.get("session_id"),
        started_at=raw.get("started_at", _utc_now()),
        sealed_at=raw.get("sealed_at"),
        sealed=bool(raw.get("sealed", False)),
        sources=[SourceDocumentNode(**s) for s in raw.get("sources", [])],
        embedding=as_node(EmbeddingNode, raw.get("embedding")),
        retrieval=as_node(RetrievalNode, raw.get("retrieval")),
        context=as_node(ContextAssemblyNode, raw.get("context")),
        generation=as_node(GenerationNode, raw.get("generation")),
        validation=as_node(ValidationNode, raw.get("validation")),
        response=as_node(ResponseNode, raw.get("response")),
    )


__all__ = [
    "ContextAssemblyNode",
    "EmbeddingNode",
    "GenerationNode",
    "LineageBuilder",
    "LineageRecord",
    "LineageStore",
    "ResponseNode",
    "RetrievalNode",
    "SourceDocumentNode",
    "ValidationNode",
]
