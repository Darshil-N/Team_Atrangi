"""
vector_db/load_guidelines.py — Ingests clinical guideline PDFs into ChromaDB.

Reads PDF files from data/guidelines/, chunks them into ~500-word segments
with 50-word overlap, and adds them to the ChromaDB collection.

Idempotent: checks existing document IDs before inserting — re-running does
NOT create duplicates.

Run once before starting the backend:
    python -m vector_db.load_guidelines

Or if guideline PDFs are not available yet, the built-in SEED_GUIDELINES
dict provides a minimal set of critical sepsis reference sentences so the
RAG agent has something to query even without PDFs.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import List, Dict

import chromadb

try:
    import PyPDF2
    _PYPDF2_AVAILABLE = True
except ImportError:
    _PYPDF2_AVAILABLE = False

from vector_db.chroma_setup import get_collection

logger = logging.getLogger(__name__)

# Path to guideline PDFs (relative to backend/ working directory)
GUIDELINES_DIR = Path("../data/guidelines")

# Chunking settings
CHUNK_WORDS    = 500   # target words per chunk
OVERLAP_WORDS  = 50    # overlap between adjacent chunks


# ─────────────────────────────────────────────────────────
# Seed guidelines — embedded directly in code.
# Used when PDF files are not available (e.g., first-run demo).
# Sourced from publicly available clinical guideline summaries.
# ─────────────────────────────────────────────────────────
SEED_GUIDELINES: List[Dict[str, str]] = [
    # Sepsis-3
    {"text": "Sepsis is defined as life-threatening organ dysfunction caused by a dysregulated host response to infection. Organ dysfunction can be identified as an acute change in total SOFA score greater than or equal to 2 points.", "source": "Sepsis-3 Consensus Definitions", "page": "1"},
    {"text": "Septic shock is a subset of sepsis in which underlying circulatory and cellular metabolism abnormalities are profound enough to substantially increase mortality. Patients can be identified by a clinical construct of sepsis with persisting hypotension requiring vasopressors to maintain a mean arterial pressure of 65 mmHg or higher.", "source": "Sepsis-3 Consensus Definitions", "page": "2"},
    {"text": "Lactate greater than 2 mmol/L suggests tissue hypoperfusion and is a key biomarker in the identification of septic shock. Serial lactate measurements are recommended to guide resuscitation.", "source": "Sepsis-3 Consensus Definitions", "page": "3"},
    {"text": "The SOFA score assesses six organ systems: respiratory (PaO2/FiO2 ratio), nervous (Glasgow Coma Scale), cardiovascular (mean arterial pressure or vasopressors), liver (bilirubin), coagulation (platelets), and renal (creatinine or urine output).", "source": "SOFA Score Guidelines", "page": "1"},
    {"text": "A SOFA score of 2 or more is associated with an in-hospital mortality risk of approximately 10%. Any increase in SOFA score by 2 or more from a patient's baseline indicates organ dysfunction attributable to sepsis.", "source": "SOFA Score Guidelines", "page": "2"},
    # Surviving Sepsis Campaign 2021
    {"text": "The Surviving Sepsis Campaign recommends that blood cultures be obtained before antibiotic therapy is initiated. At least two sets of blood cultures should be obtained with at least one drawn percutaneously.", "source": "Surviving Sepsis Campaign 2021", "page": "5"},
    {"text": "Broad-spectrum intravenous antibiotics should be started as soon as possible after recognition of sepsis and within one hour for septic shock. Antimicrobial therapy should be narrowed once pathogen identification and sensitivities are established.", "source": "Surviving Sepsis Campaign 2021", "page": "7"},
    {"text": "For patients with sepsis-induced hypoperfusion or septic shock, the Surviving Sepsis Campaign recommends an intravenous fluid resuscitation of at least 30 mL/kg of crystalloid within the first three hours.", "source": "Surviving Sepsis Campaign 2021", "page": "9"},
    {"text": "Norepinephrine is recommended as the first-line vasopressor for septic shock. The target mean arterial pressure for patients on vasopressors is 65 mmHg.", "source": "Surviving Sepsis Campaign 2021", "page": "11"},
    # Lab value interpretation
    {"text": "An elevated white blood cell count greater than 12,000 per microliter or less than 4,000 per microliter, or the presence of greater than 10 percent immature forms, is a component of the SIRS criteria and may indicate infection.", "source": "SIRS and Sepsis Criteria", "page": "1"},
    {"text": "Procalcitonin is more specific than C-reactive protein or white cell count for bacterial infection. A rising procalcitonin trend in an ICU patient should prompt reassessment for bacterial sepsis.", "source": "Biomarkers in Sepsis", "page": "3"},
    {"text": "Creatinine elevation above 0.5 mg/dL from baseline or urine output less than 0.5 mL/kg/hour for more than 6 hours indicates acute kidney injury, which is a component of the SOFA renal subscore.", "source": "SOFA Score Guidelines", "page": "3"},
    {"text": "A serum potassium greater than 6.5 mmol/L constitutes a medical emergency requiring immediate intervention. Values above 7.0 mmol/L carry a high risk of fatal arrhythmia. Values above 10 mmol/L are incompatible with life and almost certainly represent a specimen or laboratory error.", "source": "Electrolyte Emergency Guidelines", "page": "2"},
    {"text": "Thrombocytopenia, defined as platelets below 150,000 per microliter, may indicate disseminated intravascular coagulation (DIC), heparin-induced thrombocytopenia, or sepsis-related consumptive coagulopathy.", "source": "SOFA Score Guidelines", "page": "4"},
    {"text": "The quick SOFA (qSOFA) score uses three clinical criteria — respiratory rate ≥22/min, altered mentation, and systolic blood pressure ≤100 mmHg — as a rapid bedside tool. Two or more qSOFA criteria predict poor outcomes in suspected infection outside the ICU.", "source": "Sepsis-3 Consensus Definitions", "page": "5"},
]


# ─────────────────────────────────────────────────────────
# PDF chunking
# ─────────────────────────────────────────────────────────

def _extract_text_from_pdf(path: Path) -> str:
    """Extract all text from a PDF file using PyPDF2."""
    if not _PYPDF2_AVAILABLE:
        logger.warning("PyPDF2 not installed — skipping PDF: %s", path.name)
        return ""
    text_parts = []
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def _chunk_text(text: str, source: str) -> List[Dict[str, str]]:
    """
    Split text into overlapping chunks of ~CHUNK_WORDS words.
    Each chunk gets metadata: source filename and approximate page.
    """
    words  = text.split()
    chunks = []
    step   = CHUNK_WORDS - OVERLAP_WORDS

    for i in range(0, len(words), step):
        chunk_words = words[i : i + CHUNK_WORDS]
        if len(chunk_words) < 20:   # skip tiny trailing fragments
            continue
        chunk_text = " ".join(chunk_words)
        # Estimate page number based on word position (~250 words/page)
        approx_page = (i // 250) + 1
        chunks.append({
            "text":   chunk_text,
            "source": source,
            "page":   str(approx_page),
        })

    return chunks


# ─────────────────────────────────────────────────────────
# Ingestion
# ─────────────────────────────────────────────────────────

def _ingest_items(
    collection: chromadb.Collection,
    items: List[Dict[str, str]],
    id_prefix: str,
) -> int:
    """
    Add items to ChromaDB, skipping any whose IDs already exist.
    Returns the count of newly added items.
    """
    if not items:
        return 0

    # Build candidate IDs
    ids  = [f"{id_prefix}_{i}" for i in range(len(items))]
    docs = [item["text"] for item in items]
    metas = [{"source": item["source"], "page": item["page"]} for item in items]

    # Check which IDs already exist
    try:
        existing = collection.get(ids=ids)
        existing_ids = set(existing["ids"])
    except Exception:
        existing_ids = set()

    # Filter to new-only
    new_ids   = [id_ for id_ in ids if id_ not in existing_ids]
    new_docs  = [docs[i]  for i, id_ in enumerate(ids) if id_ not in existing_ids]
    new_metas = [metas[i] for i, id_ in enumerate(ids) if id_ not in existing_ids]

    if not new_ids:
        logger.info("load_guidelines: all %d items from '%s' already indexed — skipping.", len(items), id_prefix)
        return 0

    collection.add(documents=new_docs, metadatas=new_metas, ids=new_ids)
    logger.info("load_guidelines: added %d new item(s) with prefix '%s'.", len(new_ids), id_prefix)
    return len(new_ids)


def load_seed_guidelines(collection: chromadb.Collection) -> int:
    """Load the built-in seed guidelines (always run; idempotent)."""
    return _ingest_items(collection, SEED_GUIDELINES, id_prefix="seed")


def load_pdf_guidelines(collection: chromadb.Collection) -> int:
    """
    Load clinical guideline PDFs from GUIDELINES_DIR.
    Safe to call even if the directory doesn't exist — just logs a warning.
    """
    if not GUIDELINES_DIR.exists():
        logger.warning(
            "load_guidelines: PDF directory '%s' not found. "
            "Only seed guidelines will be available.",
            GUIDELINES_DIR,
        )
        return 0

    pdf_files = list(GUIDELINES_DIR.glob("*.pdf"))
    if not pdf_files:
        logger.warning("load_guidelines: no PDF files found in '%s'.", GUIDELINES_DIR)
        return 0

    total_added = 0
    for pdf_path in pdf_files:
        logger.info("load_guidelines: processing '%s' ...", pdf_path.name)
        text = _extract_text_from_pdf(pdf_path)
        if not text.strip():
            logger.warning("load_guidelines: empty text extracted from '%s' — skipping.", pdf_path.name)
            continue
        chunks = _chunk_text(text, source=pdf_path.stem)
        added  = _ingest_items(collection, chunks, id_prefix=f"pdf_{pdf_path.stem}")
        total_added += added

    return total_added


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    collection = get_collection()

    seed_count = load_seed_guidelines(collection)
    pdf_count  = load_pdf_guidelines(collection)

    print(f"\n✅ Guideline ingestion complete.")
    print(f"   Seed guidelines added : {seed_count}")
    print(f"   PDF chunks added      : {pdf_count}")
    print(f"   Total in collection   : {collection.count()}")
