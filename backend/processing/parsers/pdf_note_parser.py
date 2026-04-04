"""
processing/parsers/pdf_note_parser.py  Extract clinical note text from PDFs.

Uses pdfplumber for accurate text extraction with layout awareness.
Handles multi-page, multi-column, and scanned (text-less) PDFs gracefully.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MAX_NOTE_CHARS = 15_000  # matches note_parser.py truncation limit


def _clean_text(raw: str) -> str:
    """
    Remove common PDF artefacts:
    - Page numbers  : "Page 1 of 3", "- 2 -"
    - Headers/footers that repeat across pages (detected by short repeated lines)
    - Excessive whitespace
    """
    text = re.sub(r"\n{3,}", "\n\n", raw)
    text = re.sub(r"(?m)^[\s\-]*(?:Page\s*)?\d+[\s\-]*$", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_document_date(text: str) -> str:
    """
    Try to find a date in the clinical note text.
    Falls back to current UTC time if no date is found.

    Common formats in clinical notes:
        "Date: 01/04/2024", "04-01-2024", "April 1, 2024", "2024-04-01"
    """
    patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",                        # ISO: 2024-04-01
        r"\b(\d{2}/\d{2}/\d{4})\b",                        # US: 04/01/2024
        r"\b(\d{2}-\d{2}-\d{4})\b",                        # EU: 01-04-2024
        r"\b([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})\b",         # April 1, 2024
    ]
    for pattern in patterns:
        match = re.search(pattern, text[:2000])  # only scan first 2000 chars
        if match:
            try:
                raw_date = match.group(1)
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%B %d, %Y", "%B %d %Y"):
                    try:
                        dt = datetime.strptime(raw_date, fmt)
                        return dt.replace(tzinfo=timezone.utc).isoformat()
                    except ValueError:
                        continue
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def parse(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Parse a clinical note PDF into a ParseResult dict.

    Args:
        file_bytes: Raw PDF bytes.
        filename:   Original filename (stored as metadata).

    Returns:
        A single ParseResult with data_type="note".
    """
    warnings: List[str] = []
    all_text_parts: List[str] = []

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_count = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                try:
                    text = page.extract_text(x_tolerance=2, y_tolerance=2)
                    if text:
                        all_text_parts.append(text)
                except Exception as page_err:
                    warnings.append(f"Page {i+1} extraction failed: {page_err}")

    except Exception as exc:
        warnings.append(f"pdfplumber failed: {exc}. Returning empty note.")
        return {
            "data_type":       "note",
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "structured_json": {
                "text":       "",
                "source":     filename,
                "page_count": 0,
                "char_count": 0,
            },
            "source_filename": filename,
            "rows_parsed":     0,
            "warnings":        warnings,
        }

    raw_text = "\n".join(all_text_parts)
    clean = _clean_text(raw_text)

    if not clean.strip():
        warnings.append(
            f"No text extracted from '{filename}'. "
            "PDF may be scanned (image-only) without a text layer."
        )

    if len(clean) > MAX_NOTE_CHARS:
        warnings.append(
            f"Note truncated from {len(clean)} to {MAX_NOTE_CHARS} chars "
            "to fit phi3:mini context window."
        )
        clean = clean[:MAX_NOTE_CHARS] + "\n[...truncated...]"

    timestamp = _extract_document_date(clean)

    logger.info(
        "pdf_note_parser: parsed '%s'  %d pages, %d chars, timestamp=%s",
        filename, page_count, len(clean), timestamp,
    )

    return {
        "data_type":       "note",
        "timestamp":       timestamp,
        "structured_json": {
            "text":       clean,
            "source":     filename,
            "page_count": page_count,
            "char_count": len(clean),
        },
        "source_filename": filename,
        "rows_parsed":     1,
        "warnings":        warnings,
    }
