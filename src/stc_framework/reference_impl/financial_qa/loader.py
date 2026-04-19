"""Minimal document loader that splits a text file into retrievable chunks."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from stc_framework.adapters.embeddings.base import EmbeddingsClient
from stc_framework.adapters.vector_store.base import VectorRecord, VectorStore


def _chunk_text(
    text: str, *, chunk_chars: int = 600, overlap: int = 120
) -> list[tuple[int, str]]:
    text = re.sub(r"\s+\n", "\n", text.strip())
    chunks: list[tuple[int, str]] = []
    i = 0
    page = 1
    while i < len(text):
        end = min(len(text), i + chunk_chars)
        chunks.append((page, text[i:end]))
        i = max(end - overlap, end)
        if "\n\n" in text[i:end]:
            page += 1
    return chunks


async def load_text_document(
    *,
    source: str | Path,
    vector_store: VectorStore,
    embeddings: EmbeddingsClient,
    collection: str = "financial_docs",
    doc_name: str | None = None,
) -> int:
    """Load a plain-text document into the vector store.

    Returns the number of chunks written.
    """
    path = Path(source)
    text = path.read_text(encoding="utf-8")
    doc_name = doc_name or path.name

    await vector_store.ensure_collection(collection, embeddings.vector_size)

    chunks = _chunk_text(text)
    texts = [c[1] for c in chunks]
    vectors = await embeddings.aembed_batch(texts)

    records = [
        VectorRecord(
            id=str(uuid.uuid4()),
            vector=vec,
            text=chunk_text,
            metadata={"source": doc_name, "page": page},
        )
        for (page, chunk_text), vec in zip(chunks, vectors)
    ]
    await vector_store.upsert(collection, records)
    return len(records)
