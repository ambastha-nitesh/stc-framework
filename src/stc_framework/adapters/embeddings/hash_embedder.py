"""Deterministic hash-based embedder.

Produces reproducible vectors from a text hash. **Not** semantically
meaningful — intended as a zero-install default and test fixture so that
the pipeline works without Ollama / OpenAI.
"""

from __future__ import annotations

import hashlib
import math

from stc_framework.adapters.embeddings.base import EmbeddingsClient


class HashEmbedder(EmbeddingsClient):
    """Deterministic, dependency-free embedder."""

    def __init__(self, vector_size: int = 384) -> None:
        if vector_size < 8:
            raise ValueError("vector_size must be >= 8")
        self.vector_size = vector_size

    def _embed_sync(self, text: str) -> list[float]:
        tokens = [t for t in text.lower().split() if t]
        vec = [0.0] * self.vector_size
        if not tokens:
            # Empty text — return a small constant vector so cosine similarity
            # remains defined.
            vec[0] = 1.0
            return vec

        for token in tokens:
            # blake2b caps digest_size at 64 bytes; tile multiple digests
            # with different `person` parameters to cover larger vectors.
            data = token.encode("utf-8")
            bytes_per = 64
            filled = 0
            salt_idx = 0
            while filled < self.vector_size:
                chunk = min(bytes_per, self.vector_size - filled)
                digest = hashlib.blake2b(
                    data,
                    digest_size=chunk,
                    person=salt_idx.to_bytes(8, "little"),
                ).digest()
                for i, byte in enumerate(digest):
                    vec[filled + i] += (byte / 255.0) - 0.5
                filled += chunk
                salt_idx += 1

        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def aembed(self, text: str) -> list[float]:
        return self._embed_sync(text)

    async def aembed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_sync(t) for t in texts]

    async def healthcheck(self) -> bool:
        return True
