"""Generic Stalwart agent.

A framework-agnostic RAG pipeline:

    classify → retrieve → assemble_context → reason → format_response

External dependencies (LLM, vector store, embeddings, prompt registry) are
injected, so the same class powers the financial Q&A reference and any
other domain that follows the same shape. Every stage is wrapped in
retry + circuit breaker + timeout + bulkhead, with a fallback from
embedding-based to keyword retrieval if the embedder or vector search is
unavailable.

No LangGraph dependency at runtime — LangGraph is only required when the
spec explicitly sets ``stalwart.framework = "langgraph"`` *and* the user
installs the ``[langgraph]`` extra. The default path is a plain async
pipeline because millions of concurrent consumers should not pay for
LangGraph's graph-compilation overhead on every call.
"""

from __future__ import annotations

import re
import time
from typing import Any

from stc_framework.adapters.embeddings.base import EmbeddingsClient
from stc_framework.adapters.llm.base import ChatMessage
from stc_framework.adapters.prompts.base import PromptRegistry
from stc_framework.adapters.vector_store.base import RetrievedChunk, VectorStore
from stc_framework.config.logging import get_logger
from stc_framework.errors import EmbeddingError, VectorStoreError
from stc_framework.observability.correlation import bind_correlation
from stc_framework.observability.tracing import get_tracer
from stc_framework.resilience.bulkhead import Bulkhead
from stc_framework.resilience.circuit import get_circuit
from stc_framework.resilience.fallback import run_with_fallback
from stc_framework.resilience.retry import with_retry
from stc_framework.resilience.timeout import atimeout
from stc_framework.security.limits import get_security_limits
from stc_framework.security.sanitize import sanitize_context_chunk
from stc_framework.sentinel.classifier import DataClassifier
from stc_framework.sentinel.gateway import SentinelGateway
from stc_framework.sentinel.redaction import PIIRedactor
from stc_framework.spec.models import STCSpec
from stc_framework.stalwart.state import StalwartResult

_logger = get_logger(__name__)
_tracer = get_tracer(__name__)

_CITATION_RE = re.compile(r"\[(?:Source|Document):\s*([^\]]+)\]")


class StalwartAgent:
    def __init__(
        self,
        *,
        spec: STCSpec,
        gateway: SentinelGateway,
        vector_store: VectorStore,
        embeddings: EmbeddingsClient,
        prompt_registry: PromptRegistry,
        classifier: DataClassifier,
        prompt_name: str = "stalwart_system",
        collection_name: str = "financial_docs",
        top_k: int = 5,
        embedding_timeout_sec: float = 10.0,
        vector_timeout_sec: float = 5.0,
        embedding_max_attempts: int = 3,
        vector_max_attempts: int = 3,
        embedding_bulkhead: int = 64,
        vector_bulkhead: int = 64,
        chunk_redactor: PIIRedactor | None = None,
    ) -> None:
        self._spec = spec
        self._gateway = gateway
        self._vectors = vector_store
        self._embeddings = embeddings
        self._prompts = prompt_registry
        self._classifier = classifier
        self._prompt_name = prompt_name
        self._collection = collection_name
        self._top_k = top_k
        # Optional PII redactor for retrieved chunks — prevents
        # documents in the vector store from leaking PII to the LLM
        # (indirect PII leak).
        self._chunk_redactor = chunk_redactor

        self._embed_timeout = embedding_timeout_sec
        self._vector_timeout = vector_timeout_sec
        self._embed_max_attempts = embedding_max_attempts
        self._vector_max_attempts = vector_max_attempts
        self._embed_bulkhead = Bulkhead("embeddings", embedding_bulkhead)
        self._vector_bulkhead = Bulkhead("vector_store", vector_bulkhead)

    # ---- public -----------------------------------------------------------

    async def arun(
        self,
        query: str,
        *,
        trace_id: str = "",
        tenant_id: str | None = None,
    ) -> StalwartResult:
        started = time.perf_counter()
        result = StalwartResult(query=query, trace_id=trace_id, spec_version=self._spec.version)
        self._current_tenant_id = tenant_id  # read by _retrieve

        with bind_correlation(trace_id=trace_id, tenant_id=tenant_id, persona="stalwart"):
            with _tracer.start_as_current_span("stalwart.run") as span:
                span.set_attribute("stc.query.length", len(query))
                try:
                    await self._classify(result)
                    await self._retrieve(result)
                    self._assemble_context(result)
                    await self._reason(result, tenant_id=tenant_id)
                    self._extract_citations(result)
                except Exception as exc:
                    _logger.exception("stalwart.pipeline_error")
                    # Do not echo raw exception args back to the caller —
                    # they can contain the very user content that triggered
                    # the crash and would become a PII leak via errors.
                    result.error = type(exc).__name__
                finally:
                    result.latency_ms = (time.perf_counter() - started) * 1000.0
                    self._current_tenant_id = None
        return result

    # ---- stages -----------------------------------------------------------

    async def _classify(self, state: StalwartResult) -> None:
        state.data_tier = self._classifier.classify(state.query)

    async def _retrieve(self, state: StalwartResult) -> None:
        async def _embed_and_search() -> list[RetrievedChunk]:
            circuit_embed = get_circuit("embedding")
            circuit_vec = get_circuit("vector_store")

            async def _embed() -> list[float]:
                async with self._embed_bulkhead.acquire():
                    async with atimeout(self._embed_timeout):
                        return await self._embeddings.aembed(state.query)

            async def _search(vec: list[float]) -> list[RetrievedChunk]:
                async with self._vector_bulkhead.acquire():
                    async with atimeout(self._vector_timeout):
                        # Tenant isolation: if the caller supplied a
                        # tenant_id, pass it as a filter so a vector
                        # store shared across tenants cannot leak
                        # documents from tenant A to tenant B.
                        tenant = getattr(self, "_current_tenant_id", None)
                        filters = {"tenant_id": tenant} if tenant else None
                        return await self._vectors.search(
                            self._collection,
                            vec,
                            top_k=self._top_k,
                            filters=filters,
                        )

            try:
                vec = await circuit_embed.call(
                    lambda: with_retry(
                        _embed,
                        downstream="embedding",
                        max_attempts=self._embed_max_attempts,
                    )
                )
            except EmbeddingError:
                raise

            return await circuit_vec.call(
                lambda: with_retry(
                    lambda: _search(vec),
                    downstream="vector_store",
                    max_attempts=self._vector_max_attempts,
                )
            )

        async def _keyword_fallback() -> list[RetrievedChunk]:
            try:
                async with self._vector_bulkhead.acquire():
                    async with atimeout(self._vector_timeout):
                        tenant = getattr(self, "_current_tenant_id", None)
                        filters = {"tenant_id": tenant} if tenant else None
                        return await self._vectors.keyword_search(
                            self._collection,
                            state.query,
                            top_k=self._top_k,
                            filters=filters,
                        )
            except VectorStoreError:
                return []

        try:
            results = await run_with_fallback(
                _embed_and_search,
                [_keyword_fallback],
                label="retrieve",
            )
        except Exception as exc:
            _logger.warning("stalwart.retrieve_failed", error=repr(exc))
            state.retrieved_chunks = []
            state.retrieval_scores = []
            return

        # Defence-in-depth against *indirect* prompt injection: a
        # poisoned document may contain chat-markup (e.g. ``<|im_start|>``,
        # ``[INST]``) or zero-width tricks that try to impersonate the
        # system role to the LLM. We sanitize every chunk before it ever
        # reaches the context window, clip oversized chunks, and cap the
        # total chunk count.
        limits = get_security_limits()
        capped = results[: limits.max_chunks]
        cleaned_chunks: list[dict[str, Any]] = []
        for r in capped:
            text = sanitize_context_chunk(r.text or "")
            # Indirect PII-leak defence: retrieved documents can contain
            # the very PII we redact out of user queries. Run the
            # redactor over every chunk before the LLM ever sees it.
            if self._chunk_redactor is not None:
                try:
                    redacted = self._chunk_redactor.redact(text)
                    text = redacted.text
                except Exception:
                    # A blocked entity in a retrieved chunk should not
                    # crash the whole pipeline; drop the chunk instead.
                    _logger.warning(
                        "stalwart.chunk_dropped_blocked_pii",
                        chunk_id=r.id,
                    )
                    continue
            if len(text) > limits.max_chunk_chars:
                text = text[: limits.max_chunk_chars] + "...(truncated)"
            cleaned_chunks.append(
                {
                    "id": r.id,
                    "text": text,
                    "score": r.score,
                    "source": r.metadata.get("source", "unknown"),
                    "page": r.metadata.get("page", 0),
                    "section": r.metadata.get("section", ""),
                }
            )
        state.retrieved_chunks = cleaned_chunks
        state.retrieval_scores = [c["score"] for c in cleaned_chunks]

    def _assemble_context(self, state: StalwartResult) -> None:
        if not state.retrieved_chunks:
            state.context = "No relevant documents found."
            return

        limits = get_security_limits()
        parts: list[str] = []
        running_chars = 0
        for chunk in state.retrieved_chunks:
            source = sanitize_context_chunk(str(chunk.get("source", "unknown")))[:256]
            page = sanitize_context_chunk(str(chunk.get("page", "?")))[:32]
            section = sanitize_context_chunk(str(chunk.get("section", "")))[:128]
            header = f"[Document: {source}, Page {page}"
            if section:
                header += f", Section: {section}"
            header += "]"
            body = chunk.get("text", "")
            entry = f"{header}\n{body}"
            if running_chars + len(entry) > limits.max_context_chars:
                # Stop appending before we blow past the context budget.
                break
            parts.append(entry)
            running_chars += len(entry) + 5  # separator
        state.context = "\n\n---\n\n".join(parts)

    async def _reason(self, state: StalwartResult, *, tenant_id: str | None) -> None:
        prompt = await self._prompts.get(self._prompt_name)
        state.prompt_version = prompt.version

        messages = [
            ChatMessage(role="system", content=prompt.content),
            ChatMessage(
                role="user",
                content=(
                    "Based on the following financial document context, answer the "
                    "user's question.\n\n"
                    f"CONTEXT:\n{state.context}\n\n"
                    f"QUESTION: {state.query}\n\n"
                    "Remember: Only use information from the context above. Cite sources."
                ),
            ),
        ]

        response = await self._gateway.acompletion(
            messages,
            data_tier=state.data_tier,
            metadata={"stc_persona": "stalwart", "spec_version": state.spec_version},
            tenant_id=tenant_id,
        )
        state.response = response.content
        state.model_used = response.model
        state.cost_usd = response.cost_usd
        state.prompt_tokens = response.usage.prompt_tokens
        state.completion_tokens = response.usage.completion_tokens

    def _extract_citations(self, state: StalwartResult) -> None:
        matches = _CITATION_RE.findall(state.response or "")
        state.citations = [{"reference": m.strip()} for m in matches]
