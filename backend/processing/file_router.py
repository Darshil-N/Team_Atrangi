"""
processing/file_router.py  Detects file type and routes to correct parser.

Returns a list of ParseResult dicts ready to be inserted into parsed_data.
One file can produce multiple rows (e.g. a CSV with 7 lab rows  7 results).

Usage:
    from processing.file_router import route
    results = route(file_bytes=b"...", filename="lab.csv", hint="auto")
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Literal

logger = logging.getLogger(__name__)


ParseResult = Dict[str, Any]
"""
{
    "data_type":        "note" | "lab" | "vital",
    "timestamp":        "ISO8601 string",
    "structured_json":  { ...parser-specific payload... },
    "source_filename":  "original_filename.ext",
    "rows_parsed":      int,
    "warnings":         List[str],
}
"""

DataTypeHint = Literal["note", "lab", "vital", "auto"]



_EXT_MAP: Dict[str, str] = {
    ".txt":  "note",
    ".md":   "note",
    ".json": "auto",   # JSON carries its own type hint
    ".csv":  "lab",
    ".xlsx": "lab",
    ".xls":  "lab",
    ".pdf":  "pdf",    # further disambiguation happens inside route()
}


def _detect_ext(filename: str) -> str:
    """Return the lowercased file extension, e.g. '.pdf'."""
    return Path(filename).suffix.lower()


def _pdf_has_tables(file_bytes: bytes) -> bool:
    """
    Quick heuristic: does this PDF contain extractable tables?
    Used to route between pdf_note_parser and pdf_lab_parser.
    """
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages[:3]:   # check first 3 pages only
                if page.extract_tables():
                    return True
        return False
    except Exception:
        return False   # on any error, default to note parser


def route(
    file_bytes: bytes,
    filename: str,
    hint: DataTypeHint = "auto",
) -> List[ParseResult]:
    """
    Detect file type and parse into a list of ParseResult dicts.

    Args:
        file_bytes: Raw bytes of the uploaded file.
        filename:   Original filename (used for extension detection + metadata).
        hint:       User-specified type ("note"/"lab"/"vital") or "auto".

    Returns:
        List of ParseResult dicts. Most parsers return 1 result;
        CSV/Excel parsers return one result per row.

    Raises:
        ValueError: if the file type is completely unsupported.
    """
    ext = _detect_ext(filename)

    if ext not in _EXT_MAP:
        raise ValueError(
            f"Unsupported file type '{ext}'. "
            f"Supported: {', '.join(_EXT_MAP.keys())}"
        )

    parser_key = _EXT_MAP[ext]
    logger.info("file_router: %s  parser_key=%s, hint=%s", filename, parser_key, hint)

    if ext == ".json":
        from processing.parsers.text_parser import parse as parse_text
        data_type = hint if hint != "auto" else "note"
        return [parse_text(file_bytes, filename, data_type=data_type)]

    if parser_key == "lab":
        from processing.parsers.lab_csv_parser import parse as parse_csv
        return parse_csv(file_bytes, filename)

    if parser_key == "pdf":
        if hint == "note":
            from processing.parsers.pdf_note_parser import parse as parse_pdf_note
            return [parse_pdf_note(file_bytes, filename)]
        if hint == "lab" or _pdf_has_tables(file_bytes):
            from processing.parsers.pdf_lab_parser import parse as parse_pdf_lab
            return [parse_pdf_lab(file_bytes, filename)]
        from processing.parsers.pdf_note_parser import parse as parse_pdf_note
        return [parse_pdf_note(file_bytes, filename)]

    if parser_key == "note":
        from processing.parsers.text_parser import parse as parse_text
        data_type = hint if hint != "auto" else "note"
        return [parse_text(file_bytes, filename, data_type=data_type)]

    raise ValueError(f"Could not determine parser for '{filename}' with hint='{hint}'")
