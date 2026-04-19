"""
STC Framework - Document Loader

Loads financial documents into the local vector store (Qdrant).
Embeddings are computed locally via Ollama to ensure data sovereignty.

Usage:
    python reference-impl/scripts/load_documents.py [--doc-dir path/to/docs]

By default, loads sample SEC filings from the reference-impl/documents/ directory.
"""

import os
import sys
import json
import hashlib
import logging
import argparse
from pathlib import Path
from typing import Generator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from spec.loader import load_spec

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("stc.loader")


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> Generator[dict, None, None]:
    """Split text into overlapping chunks for embedding."""
    words = text.split()
    chunk_words = chunk_size // 5  # Approximate words per chunk
    overlap_words = overlap // 5
    
    for i in range(0, len(words), chunk_words - overlap_words):
        chunk = " ".join(words[i:i + chunk_words])
        if len(chunk.strip()) > 50:  # Skip tiny chunks
            yield {
                "text": chunk,
                "start_word": i,
                "end_word": min(i + chunk_words, len(words)),
            }


def embed_text(text: str, endpoint: str, model: str) -> list[float]:
    """Compute embedding locally via Ollama."""
    import requests
    
    response = requests.post(
        f"{endpoint}/api/embeddings",
        json={"model": model, "prompt": text},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["embedding"]


def load_documents(doc_dir: str, spec_path: str = "spec/stc-spec.yaml"):
    """Load all documents from a directory into Qdrant."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import VectorParams, Distance, PointStruct
    
    spec = load_spec(spec_path)
    
    # Configuration from spec
    vs_config = spec.data_sovereignty.get("vector_store", {})
    embed_config = spec.data_sovereignty.get("embedding_model", {})
    
    qdrant_host = vs_config.get("host", "http://localhost:6333")
    collection_name = "financial_docs"
    embed_endpoint = embed_config.get("endpoint", "http://localhost:11434")
    embed_model = embed_config.get("model", "bge-large-en-v1.5")
    
    logger.info(f"Connecting to Qdrant at {qdrant_host}")
    client = QdrantClient(url=qdrant_host)
    
    # Get embedding dimension from a test embedding
    logger.info(f"Testing embedding model: {embed_model}")
    test_embedding = embed_text("test", embed_endpoint, embed_model)
    embed_dim = len(test_embedding)
    logger.info(f"Embedding dimension: {embed_dim}")
    
    # Create or recreate collection
    collections = [c.name for c in client.get_collections().collections]
    if collection_name in collections:
        logger.info(f"Deleting existing collection: {collection_name}")
        client.delete_collection(collection_name)
    
    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=embed_dim, distance=Distance.COSINE),
    )
    
    # Process documents
    doc_path = Path(doc_dir)
    total_chunks = 0
    
    for file_path in sorted(doc_path.glob("*.txt")):
        logger.info(f"Processing: {file_path.name}")
        
        with open(file_path, "r") as f:
            text = f.read()
        
        chunks = list(chunk_text(text))
        logger.info(f"  Split into {len(chunks)} chunks")
        
        points = []
        for i, chunk in enumerate(chunks):
            embedding = embed_text(chunk["text"], embed_endpoint, embed_model)
            
            point_id = hashlib.md5(
                f"{file_path.name}:{i}".encode()
            ).hexdigest()[:16]
            point_id_int = int(point_id, 16) % (2**63)
            
            points.append(PointStruct(
                id=point_id_int,
                vector=embedding,
                payload={
                    "text": chunk["text"],
                    "source": file_path.stem,
                    "page": i // 3 + 1,  # Approximate page number
                    "section": f"chunk_{i}",
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                },
            ))
        
        # Batch upsert
        batch_size = 100
        for j in range(0, len(points), batch_size):
            batch = points[j:j + batch_size]
            client.upsert(collection_name=collection_name, points=batch)
        
        total_chunks += len(chunks)
        logger.info(f"  Loaded {len(chunks)} chunks")
    
    logger.info(f"\nDone! Total chunks loaded: {total_chunks}")
    logger.info(f"Collection: {collection_name} at {qdrant_host}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load financial documents into STC vector store")
    parser.add_argument("--doc-dir", default="reference-impl/documents/", help="Directory containing documents")
    parser.add_argument("--spec", default="spec/stc-spec.yaml", help="Path to STC spec")
    args = parser.parse_args()
    
    load_documents(args.doc_dir, args.spec)
