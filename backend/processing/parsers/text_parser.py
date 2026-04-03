"""
processing/parsers/text_parser.py — Parse plain text (.txt) and JSON (.json) uploads.

- .txt files: wrapped as note structured_json
- .json files: validated and inserted as-is (user supplies the structure)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


def parse(
    file_bytes: bytes,
    filename: str,
    data_type: str = "note",
) -> Dict[str, Any]:
    """
    Parse a text or JSON file into a ParseResult dict.

    Args:
        file_bytes: Raw file bytes.
        filename:   Original filename.
        data_type:  "note" | "lab" | "vital" — caller-specified type.

    Returns:
        A single ParseResult dict.
    """
    warnings = []
    ext = filename.lower().rsplit(".", 1)[-1]

    # ── JSON mode ─────────────────────────────────────────
    if ext == "json":
        try:
            payload = json.loads(file_bytes.decode("utf-8"))
            # If the JSON already contains "data_type", honour it
            if isinstance(payload, dict):
                resolved_type = payload.get("data_type", data_type)
                ts = payload.get("timestamp", datetime.now(timezone.utc).isoformat())
                structured = payload.get("structured_json", payload)
            else:
                resolved_type = data_type
                ts = datetime.now(timezone.utc).isoformat()
                structured = {"raw": payload}
            logger.info("text_parser: JSON '%s' — type=%s", filename, resolved_type)
            return {
                "data_type":       resolved_type,
                "timestamp":       ts,
                "structured_json": structured,
                "source_filename": filename,
                "rows_parsed":     1,
                "warnings":        warnings,
            }
        except json.JSONDecodeError as exc:
            warnings.append(f"Invalid JSON: {exc}. Treating as plain text note.")
            # Fall through to plain text handling

    # ── Plain text mode ───────────────────────────────────
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = file_bytes.decode(encoding).strip()
            break
        except UnicodeDecodeError:
            continue
    else:
        text = file_bytes.decode("utf-8", errors="replace").strip()
        warnings.append("File encoding was not UTF-8 — some characters may be replaced.")

    if not text:
        warnings.append(f"File '{filename}' appears to be empty.")

    # Truncate very long plain-text notes
    MAX_CHARS = 15_000
    if len(text) > MAX_CHARS:
        warnings.append(f"Text truncated from {len(text)} to {MAX_CHARS} chars.")
        text = text[:MAX_CHARS] + "\n[...truncated...]"

    logger.info("text_parser: TXT '%s' — %d chars, type=%s", filename, len(text), data_type)

    return {
        "data_type":       data_type,
        "timestamp":       datetime.now(timezone.utc).isoformat(),
        "structured_json": {
            "text":       text,
            "source":     filename,
            "char_count": len(text),
        },
        "source_filename": filename,
        "rows_parsed":     1 if text else 0,
        "warnings":        warnings,
    }
