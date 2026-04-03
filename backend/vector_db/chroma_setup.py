"""
vector_db/chroma_setup.py — ChromaDB initialisation helper.

Creates (or opens) the persistent ChromaDB collection for clinical guidelines.
Run once before load_guidelines.py; safe to call repeatedly (idempotent).

Usage:
    python -m vector_db.chroma_setup          # standalone init
    from vector_db.chroma_setup import get_collection  # in other modules
"""
from __future__ import annotations

import logging
import os

# Fix for Windows: sentence-transformers tries to create symlinks in the
# HuggingFace cache, which requires elevated permissions on Windows.
# Setting this env var before import makes it use copies instead.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HUGGINGFACE_HUB_VERBOSITY", "warning")

import chromadb
from chromadb.utils import embedding_functions

import config

logger = logging.getLogger(__name__)


def get_collection() -> chromadb.Collection:
    """
    Return the clinical_guidelines ChromaDB collection.

    - Creates the persistent client at CHROMA_PERSIST_PATH if it doesn't exist.
    - Creates the collection if it doesn't exist.
    - Reuses the existing collection if it does — completely idempotent.

    Embedding model: all-MiniLM-L6-v2
        • 384-dim dense vectors
        • ~80 MB download on first use (cached afterward)
        • Fast on CPU — no GPU required for embedding
    """
    client = chromadb.PersistentClient(path=config.CHROMA_PERSIST_PATH)

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )

    # get_or_create_collection is idempotent — safe to call multiple times
    collection = client.get_or_create_collection(
        name=config.CHROMA_COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},   # cosine similarity for clinical text
    )

    logger.info(
        "ChromaDB collection '%s' ready at '%s' — %d document(s) indexed.",
        config.CHROMA_COLLECTION_NAME,
        config.CHROMA_PERSIST_PATH,
        collection.count(),
    )

    return collection


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    col = get_collection()
    print(f"✅ ChromaDB ready. Collection '{col.name}' has {col.count()} documents.")
