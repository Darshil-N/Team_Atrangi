"""
agents/rag_agent.py — Agent 3: Clinical Guideline RAG Retriever.

Queries the ChromaDB vector store for guidelines most relevant to
the patient's current symptoms and lab trends. No LLM call in this
agent — pure vector similarity. Fast, deterministic, citable.

Usage:
    from agents.rag_agent import run
    result = await run(state, symptoms_output, lab_output)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from vector_db.chroma_setup import get_collection
from processing.state_builder import PatientState

logger = logging.getLogger(__name__)

# Number of guideline chunks to retrieve per query
TOP_K = 5

# Minimum relevance score to include a result (cosine similarity, 0–1)
MIN_RELEVANCE_SCORE = 0.30


# ─────────────────────────────────────────────────────────
# Output type
# ─────────────────────────────────────────────────────────

RAGOutput = Dict[str, Any]
"""
Shape returned by run():
{
    "guidelines": [
        {
            "title":            "Sepsis-3 Consensus Definitions",
            "citation":         "Lactate > 2 mmol/L suggests tissue hypoperfusion...",
            "relevance_score":  0.92,
            "source_page":      "3",
        },
        ...
    ],
    "query_used": str,   # the query string sent to ChromaDB (useful for debugging)
    "warnings":   [],
}
"""


# ─────────────────────────────────────────────────────────
# Query builder
# ─────────────────────────────────────────────────────────

def _build_query(
    symptoms_output: Dict[str, Any],
    lab_output: Dict[str, Any],
) -> str:
    """
    Construct a natural-language query from agent 1 + agent 2 outputs.
    The query string is embedded by ChromaDB and matched against guidelines.

    Strategy: include symptom names + rising/falling lab parameter names
    so the embedding captures both clinical features and trend context.
    """
    parts: List[str] = []

    # Symptoms
    symptoms = symptoms_output.get("symptoms", [])
    if symptoms:
        symptom_texts = [s.get("text", "") for s in symptoms if s.get("text")]
        if symptom_texts:
            parts.append("Symptoms: " + ", ".join(symptom_texts))

    # Rising or critically-altered labs
    trends = lab_output.get("trends", {})
    rising  = [p for p, t in trends.items() if t.get("direction") == "rising"]
    falling = [p for p, t in trends.items() if t.get("direction") == "falling"]
    if rising:
        parts.append("Rising lab parameters: " + ", ".join(rising))
    if falling:
        parts.append("Falling lab parameters: " + ", ".join(falling))

    # Outlier parameters
    outliers = lab_output.get("outliers", [])
    if outliers:
        outlier_params = [o.get("parameter", "") for o in outliers if o.get("parameter")]
        if outlier_params:
            parts.append("Abnormal values requiring verification: " + ", ".join(outlier_params))

    # Fallback if there's nothing useful yet
    if not parts:
        parts.append("ICU patient sepsis organ dysfunction risk assessment")

    return ". ".join(parts)


# ─────────────────────────────────────────────────────────
# Public entry point (called by orchestrator)
# ─────────────────────────────────────────────────────────

async def run(
    state: PatientState,
    symptoms_output: Dict[str, Any],
    lab_output: Dict[str, Any],
) -> RAGOutput:
    """
    Retrieve the most relevant clinical guidelines for this patient's
    current clinical picture.

    Args:
        state:           Unified patient state dict (used only for patient_id in logs).
        symptoms_output: Output from note_parser.run().
        lab_output:      Output from lab_mapper.run().

    Returns:
        RAGOutput with guidelines list, query string, and any warnings.
    """
    patient_id: str = state.get("patient_id", "unknown")
    warnings: List[str] = []

    logger.info("rag_agent: starting — patient=%s", patient_id)

    # Build the semantic query from agent outputs
    query = _build_query(symptoms_output, lab_output)
    logger.debug("rag_agent: query = %s", query)

    guidelines: List[Dict[str, Any]] = []

    try:
        collection = get_collection()
        doc_count  = collection.count()

        if doc_count == 0:
            msg = (
                "rag_agent: ChromaDB collection is empty. "
                "Run `python -m vector_db.load_guidelines` first."
            )
            logger.warning(msg)
            warnings.append(msg)
            return {"guidelines": [], "query_used": query, "warnings": warnings}

        results = collection.query(
            query_texts=[query],
            n_results=min(TOP_K, doc_count),   # don't request more than we have
            include=["documents", "metadatas", "distances"],
        )

        # Unpack results — ChromaDB returns lists-of-lists (one per query)
        docs      = results.get("documents",  [[]])[0]
        metadatas = results.get("metadatas",  [[]])[0]
        distances = results.get("distances",  [[]])[0]

        for doc, meta, dist in zip(docs, metadatas, distances):
            # ChromaDB with cosine space returns distances as 1 - cosine_similarity
            # Convert to similarity score (0 = unrelated, 1 = identical)
            relevance_score = round(1.0 - float(dist), 4)

            if relevance_score < MIN_RELEVANCE_SCORE:
                logger.debug(
                    "rag_agent: skipping low-relevance result (score=%.3f): %s...",
                    relevance_score, doc[:60],
                )
                continue

            guidelines.append({
                "title":           meta.get("source", "Unknown Guideline"),
                "citation":        doc,
                "relevance_score": relevance_score,
                "source_page":     meta.get("page", "n/a"),
            })

        # Sort by descending relevance
        guidelines.sort(key=lambda g: g["relevance_score"], reverse=True)

        logger.info(
            "rag_agent: done — patient=%s, retrieved=%d guideline(s)",
            patient_id, len(guidelines),
        )

    except Exception as exc:
        msg = f"rag_agent: ChromaDB query failed: {exc}"
        logger.error(msg)
        warnings.append(msg)

    return {
        "guidelines": guidelines,
        "query_used": query,
        "warnings":   warnings,
    }
