"""Embedding client adapters."""

from stc_framework.adapters.embeddings.base import EmbeddingsClient
from stc_framework.adapters.embeddings.hash_embedder import HashEmbedder

__all__ = ["EmbeddingsClient", "HashEmbedder"]
