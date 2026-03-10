"""
STC Framework — Data Lineage Tracker
governance/data_lineage.py

End-to-end data lineage tracking from source document to AI response.
Produces a connected lineage graph for every request:
  Source Document → Embedding → Vector Index → Retrieval → Context Assembly
  → LLM Generation → Critic Validation → Response Delivery

Satisfies: EU AI Act Art. 12, FINRA Rule 3110, BCBS 239.
Integrates with OTel trace IDs for correlation with observability.
"""

import json
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("stc.governance.lineage")


# ── Lineage Nodes ───────────────────────────────────────────────────────────

@dataclass
class SourceDocumentNode:
    doc_id: str
    title: str = ""
    source_system: str = ""
    version: str = ""
    classification_tier: str = "public"
    ingestion_date: str = ""
    quality_score: float = 0.0

@dataclass
class EmbeddingNode:
    model_id: str
    model_version: str = ""
    dimensions: int = 0
    chunk_strategy: str = "fixed_size"
    chunk_ids: List[str] = field(default_factory=list)

@dataclass
class RetrievalNode:
    query_hash: str
    top_k: int = 5
    retrieved_docs: List[Dict[str, Any]] = field(default_factory=list)  # [{doc_id, chunk_id, score}]
    latency_ms: float = 0.0

@dataclass
class ContextAssemblyNode:
    context_tokens: int = 0
    docs_included: List[str] = field(default_factory=list)
    docs_excluded: List[Dict[str, str]] = field(default_factory=list)  # [{doc_id, reason}]
    pii_redactions: int = 0

@dataclass
class GenerationNode:
    model_id: str
    provider: str = ""
    model_version: str = ""
    prompt_template_id: str = ""
    prompt_version: str = ""
    temperature: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0

@dataclass
class ValidationNode:
    validators_applied: List[str] = field(default_factory=list)
    verdict: str = "pass"  # pass | fail | escalate
    violations: List[str] = field(default_factory=list)
    escalation_level: str = "nominal"

@dataclass
class ResponseNode:
    response_hash: str = ""
    pii_restorations: int = 0
    latency_ms: float = 0.0


# ── Lineage Record ──────────────────────────────────────────────────────────

@dataclass
class LineageRecord:
    """Complete end-to-end lineage for a single request."""
    lineage_id: str              # = OTel trace_id
    request_id: str
    session_id: str
    timestamp: str
    # Pipeline nodes
    source_documents: List[SourceDocumentNode] = field(default_factory=list)
    embedding: Optional[EmbeddingNode] = None
    retrieval: Optional[RetrievalNode] = None
    context_assembly: Optional[ContextAssemblyNode] = None
    generation: Optional[GenerationNode] = None
    validation: Optional[ValidationNode] = None
    response: Optional[ResponseNode] = None
    # Metadata
    data_tier: str = "public"
    total_latency_ms: float = 0.0
    status: str = "complete"  # complete | partial | failed

    def to_dict(self) -> Dict[str, Any]:
        def _node(n):
            if n is None: return None
            if isinstance(n, list): return [_node(i) for i in n]
            return {k: v for k, v in n.__dict__.items()} if hasattr(n, '__dict__') else n

        return {
            "lineage_id": self.lineage_id, "request_id": self.request_id,
            "session_id": self.session_id, "timestamp": self.timestamp,
            "source_documents": _node(self.source_documents),
            "embedding": _node(self.embedding), "retrieval": _node(self.retrieval),
            "context_assembly": _node(self.context_assembly),
            "generation": _node(self.generation), "validation": _node(self.validation),
            "response": _node(self.response),
            "data_tier": self.data_tier, "total_latency_ms": self.total_latency_ms,
            "status": self.status,
        }


# ── Lineage Builder ─────────────────────────────────────────────────────────

class LineageBuilder:
    """
    Builds a lineage record incrementally as the request flows through the pipeline.

    Usage (called by Stalwart agent at each pipeline stage):
        builder = LineageBuilder(trace_id, request_id, session_id)
        builder.add_source_documents([...])
        builder.add_embedding(model_id="bge-small", ...)
        builder.add_retrieval(query_hash="...", top_k=5, results=[...])
        builder.add_generation(model_id="claude-sonnet", ...)
        builder.add_validation(validators=[...], verdict="pass")
        builder.add_response(response_hash="...")
        record = builder.build()
    """

    def __init__(self, trace_id: str, request_id: str, session_id: str,
                 data_tier: str = "public"):
        self._record = LineageRecord(
            lineage_id=trace_id, request_id=request_id, session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(), data_tier=data_tier,
        )
        self._start_time = time.time()

    def add_source_documents(self, docs: List[Dict[str, Any]]):
        self._record.source_documents = [
            SourceDocumentNode(
                doc_id=d.get("doc_id", ""), title=d.get("title", ""),
                source_system=d.get("source_system", ""), version=d.get("version", ""),
                classification_tier=d.get("classification_tier", "public"),
                ingestion_date=d.get("ingestion_date", ""),
                quality_score=d.get("quality_score", 0.0),
            ) for d in docs
        ]

    def add_embedding(self, model_id: str, model_version: str = "",
                      dimensions: int = 0, chunk_strategy: str = "fixed_size",
                      chunk_ids: List[str] = None):
        self._record.embedding = EmbeddingNode(
            model_id=model_id, model_version=model_version,
            dimensions=dimensions, chunk_strategy=chunk_strategy,
            chunk_ids=chunk_ids or [],
        )

    def add_retrieval(self, query_hash: str, top_k: int,
                      results: List[Dict[str, Any]], latency_ms: float = 0.0):
        self._record.retrieval = RetrievalNode(
            query_hash=query_hash, top_k=top_k,
            retrieved_docs=results, latency_ms=latency_ms,
        )

    def add_context_assembly(self, context_tokens: int, docs_included: List[str],
                             docs_excluded: List[Dict[str, str]] = None,
                             pii_redactions: int = 0):
        self._record.context_assembly = ContextAssemblyNode(
            context_tokens=context_tokens, docs_included=docs_included,
            docs_excluded=docs_excluded or [], pii_redactions=pii_redactions,
        )

    def add_generation(self, model_id: str, provider: str = "",
                       model_version: str = "", prompt_template_id: str = "",
                       prompt_version: str = "", temperature: float = 0.0,
                       tokens_in: int = 0, tokens_out: int = 0,
                       latency_ms: float = 0.0):
        self._record.generation = GenerationNode(
            model_id=model_id, provider=provider, model_version=model_version,
            prompt_template_id=prompt_template_id, prompt_version=prompt_version,
            temperature=temperature, tokens_in=tokens_in, tokens_out=tokens_out,
            latency_ms=latency_ms,
        )

    def add_validation(self, validators: List[str], verdict: str,
                       violations: List[str] = None, escalation: str = "nominal"):
        self._record.validation = ValidationNode(
            validators_applied=validators, verdict=verdict,
            violations=violations or [], escalation_level=escalation,
        )

    def add_response(self, response_hash: str, pii_restorations: int = 0,
                     latency_ms: float = 0.0):
        self._record.response = ResponseNode(
            response_hash=response_hash, pii_restorations=pii_restorations,
            latency_ms=latency_ms,
        )

    def build(self) -> LineageRecord:
        self._record.total_latency_ms = (time.time() - self._start_time) * 1000
        # Determine completeness
        stages = [self._record.source_documents, self._record.embedding,
                  self._record.retrieval, self._record.generation,
                  self._record.validation, self._record.response]
        filled = sum(1 for s in stages if s)
        self._record.status = "complete" if filled >= 5 else ("partial" if filled >= 3 else "failed")
        return self._record


# ── Lineage Store ───────────────────────────────────────────────────────────

class LineageStore:
    """
    Stores and queries lineage records.

    Supports queries by: lineage_id, document_id, model_id, session_id, time range.
    In production, backed by a database. In dev, in-memory.
    """

    def __init__(self, audit_callback: Optional[Callable] = None):
        self._records: Dict[str, LineageRecord] = {}
        self._doc_index: Dict[str, List[str]] = {}  # doc_id → [lineage_ids]
        self._model_index: Dict[str, List[str]] = {}  # model_id → [lineage_ids]
        self._session_index: Dict[str, List[str]] = {}  # session_id → [lineage_ids]
        self._audit_callback = audit_callback

    def store(self, record: LineageRecord):
        self._records[record.lineage_id] = record
        # Build indexes
        for doc in record.source_documents:
            self._doc_index.setdefault(doc.doc_id, []).append(record.lineage_id)
        if record.generation:
            self._model_index.setdefault(record.generation.model_id, []).append(record.lineage_id)
        self._session_index.setdefault(record.session_id, []).append(record.lineage_id)

        if self._audit_callback:
            self._audit_callback({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "component": "governance.lineage",
                "event_type": "lineage_stored",
                "details": {"lineage_id": record.lineage_id, "status": record.status,
                            "docs": len(record.source_documents)},
            })

    def get(self, lineage_id: str) -> Optional[LineageRecord]:
        return self._records.get(lineage_id)

    def by_document(self, doc_id: str) -> List[LineageRecord]:
        ids = self._doc_index.get(doc_id, [])
        return [self._records[lid] for lid in ids if lid in self._records]

    def by_model(self, model_id: str) -> List[LineageRecord]:
        ids = self._model_index.get(model_id, [])
        return [self._records[lid] for lid in ids if lid in self._records]

    def by_session(self, session_id: str) -> List[LineageRecord]:
        ids = self._session_index.get(session_id, [])
        return [self._records[lid] for lid in ids if lid in self._records]

    def coverage_report(self) -> Dict[str, Any]:
        total = len(self._records)
        complete = sum(1 for r in self._records.values() if r.status == "complete")
        partial = sum(1 for r in self._records.values() if r.status == "partial")
        failed = sum(1 for r in self._records.values() if r.status == "failed")
        unique_docs = len(self._doc_index)
        unique_models = len(self._model_index)
        return {
            "total_lineage_records": total, "complete": complete,
            "partial": partial, "failed": failed,
            "coverage_rate": complete / total if total > 0 else 0,
            "unique_documents_referenced": unique_docs,
            "unique_models_referenced": unique_models,
        }

    def impact_analysis(self, doc_id: str) -> Dict[str, Any]:
        """If a document is updated/removed, what responses are affected?"""
        records = self.by_document(doc_id)
        return {
            "doc_id": doc_id,
            "responses_affected": len(records),
            "sessions_affected": len(set(r.session_id for r in records)),
            "models_involved": list(set(r.generation.model_id for r in records if r.generation)),
            "date_range": {
                "earliest": min(r.timestamp for r in records) if records else None,
                "latest": max(r.timestamp for r in records) if records else None,
            },
        }


# ── Demo ────────────────────────────────────────────────────────────────────

def demo():
    print("=" * 70)
    print("STC Data Lineage Tracker — Demo")
    print("=" * 70)

    audit_log = []
    store = LineageStore(audit_callback=lambda e: audit_log.append(e))

    # Simulate 3 requests through the pipeline
    print("\n▸ Simulating 3 requests with full lineage...")

    for i in range(3):
        trace_id = hashlib.sha256(f"trace-{i}-{time.time()}".encode()).hexdigest()[:16]
        builder = LineageBuilder(trace_id, f"req-{i+1}", "session-abc", "internal")

        builder.add_source_documents([
            {"doc_id": "acme-10k-fy2024", "title": "ACME Corp 10-K FY2024",
             "source_system": "EDGAR", "version": "1.0", "classification_tier": "public",
             "ingestion_date": "2026-03-01", "quality_score": 92.5},
            {"doc_id": "acme-earnings-q4", "title": "ACME Q4 Earnings Call Transcript",
             "source_system": "Refinitiv", "version": "1.0", "classification_tier": "internal",
             "quality_score": 88.0},
        ])

        builder.add_embedding(model_id="BAAI/bge-small-en-v1.5", model_version="1.5",
                              dimensions=384, chunk_strategy="semantic",
                              chunk_ids=[f"chunk-{i}-{j}" for j in range(4)])

        builder.add_retrieval(
            query_hash=hashlib.sha256(f"query-{i}".encode()).hexdigest()[:12],
            top_k=5,
            results=[
                {"doc_id": "acme-10k-fy2024", "chunk_id": f"chunk-{i}-0", "score": 0.92},
                {"doc_id": "acme-10k-fy2024", "chunk_id": f"chunk-{i}-1", "score": 0.87},
                {"doc_id": "acme-earnings-q4", "chunk_id": f"chunk-{i}-2", "score": 0.81},
            ],
            latency_ms=35.2
        )

        builder.add_context_assembly(context_tokens=2048,
                                     docs_included=["acme-10k-fy2024", "acme-earnings-q4"],
                                     pii_redactions=2 if i == 1 else 0)

        model = "anthropic/claude-sonnet-4" if i != 2 else "local/llama-3.1-8b"
        builder.add_generation(
            model_id=model, provider="anthropic" if i != 2 else "local",
            prompt_template_id="financial_qa_v3", prompt_version="3.2",
            temperature=0.1, tokens_in=2200, tokens_out=350, latency_ms=2100.0)

        builder.add_validation(
            validators=["numerical_accuracy", "hallucination_check", "scope_validator"],
            verdict="pass" if i != 1 else "fail",
            violations=["numerical_discrepancy"] if i == 1 else [])

        builder.add_response(
            response_hash=hashlib.sha256(f"response-{i}".encode()).hexdigest()[:12],
            pii_restorations=2 if i == 1 else 0)

        record = builder.build()
        store.store(record)
        print(f"  Request {i+1}: lineage={record.lineage_id}, status={record.status}, "
              f"docs={len(record.source_documents)}, model={model}")

    # Lineage queries
    print("\n▸ Query: Which responses used document 'acme-10k-fy2024'?")
    by_doc = store.by_document("acme-10k-fy2024")
    print(f"  Found: {len(by_doc)} responses")

    print("\n▸ Query: Which responses used model 'anthropic/claude-sonnet-4'?")
    by_model = store.by_model("anthropic/claude-sonnet-4")
    print(f"  Found: {len(by_model)} responses")

    print("\n▸ Query: Full lineage for session 'session-abc'")
    by_session = store.by_session("session-abc")
    print(f"  Found: {len(by_session)} requests in session")

    # Impact analysis
    print("\n▸ Impact analysis: What if 'acme-10k-fy2024' is updated?")
    impact = store.impact_analysis("acme-10k-fy2024")
    print(f"  Responses affected: {impact['responses_affected']}")
    print(f"  Sessions affected: {impact['sessions_affected']}")
    print(f"  Models involved: {impact['models_involved']}")

    # Single lineage detail
    print("\n▸ Detailed lineage for request 1:")
    record = by_session[0]
    rd = record.to_dict()
    print(f"  Sources: {[d['doc_id'] for d in rd['source_documents']]}")
    print(f"  Embedding: {rd['embedding']['model_id']} ({rd['embedding']['dimensions']}d)")
    print(f"  Retrieval: {len(rd['retrieval']['retrieved_docs'])} docs, {rd['retrieval']['latency_ms']}ms")
    print(f"  Context: {rd['context_assembly']['context_tokens']} tokens, "
          f"{rd['context_assembly']['pii_redactions']} PII redactions")
    print(f"  Generation: {rd['generation']['model_id']}, "
          f"{rd['generation']['tokens_in']}→{rd['generation']['tokens_out']} tokens, "
          f"{rd['generation']['latency_ms']}ms")
    print(f"  Validation: {rd['validation']['verdict']} "
          f"({', '.join(rd['validation']['validators_applied'])})")

    # Coverage report
    print("\n▸ Lineage coverage report:")
    cov = store.coverage_report()
    print(f"  Total records: {cov['total_lineage_records']}")
    print(f"  Complete: {cov['complete']}, Partial: {cov['partial']}, Failed: {cov['failed']}")
    print(f"  Coverage rate: {cov['coverage_rate']:.0%}")
    print(f"  Unique documents: {cov['unique_documents_referenced']}")
    print(f"  Unique models: {cov['unique_models_referenced']}")

    print(f"\n▸ Audit events: {len(audit_log)}")

    print("\n" + "=" * 70)
    print("✓ Data lineage tracker demo complete")
    print("=" * 70)


if __name__ == "__main__":
    demo()
