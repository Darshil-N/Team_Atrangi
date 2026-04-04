"""
processing/parsers/pdf_lab_parser.py  Extract structured lab values from PDF lab reports.

Two-strategy approach:
  Strategy A: pdfplumber table extraction (works for digitally-generated lab PDFs)
  Strategy B: regex pattern matching on raw text (fallback for non-table PDFs)
"""
from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


_LAB_PARAMS: List[Tuple[str, List[str], str]] = [
    ("WBC",          ["WBC", "White Blood Cell", "Leukocyte"],             "K/uL"),
    ("Hemoglobin",   ["Hemoglobin", "Haemoglobin", "Hgb", "Hb"],          "g/dL"),
    ("Platelets",    ["Platelet", "PLT", "Thrombocyte"],                   "K/uL"),
    ("Lactate",      ["Lactate", "Lactic Acid", "Lac"],                    "mmol/L"),
    ("Creatinine",   ["Creatinine", "Creat", "Cr"],                        "mg/dL"),
    ("BUN",          ["BUN", "Urea Nitrogen", "Blood Urea"],               "mg/dL"),
    ("Potassium",    ["Potassium", "K\\+?", "Serum Potassium"],            "mmol/L"),
    ("Sodium",       ["Sodium", "Na\\+?", "Serum Sodium"],                 "mmol/L"),
    ("Glucose",      ["Glucose", "Gluc", "Blood Glucose"],                 "mg/dL"),
    ("pH",           ["pH", "Arterial pH", "Blood pH"],                    ""),
    ("Bicarbonate",  ["Bicarbonate", "HCO3", "Bicarb"],                   "mmol/L"),
    ("Bilirubin",    ["Bilirubin", "Total Bilirubin", "T.Bili", "TBili"], "mg/dL"),
    ("CRP",          ["CRP", "C-Reactive Protein", "C Reactive Protein"], "mg/L"),
    ("Procalcitonin",["Procalcitonin", "PCT"],                             "ng/mL"),
    ("Troponin",     ["Troponin", "Troponin I", "Troponin T", "TropI"],   "ng/mL"),
    ("INR",          ["INR", "PT/INR", "PT INR"],                          ""),
    ("SpO2",         ["SpO2", "Oxygen Saturation", "O2 Sat"],              "%"),
    ("PaO2",         ["PaO2", "Partial Pressure O2"],                     "mmHg"),
    ("FiO2",         ["FiO2", "Fraction Inspired O2"],                    "%"),
]

_LAB_PATTERNS: List[Tuple[str, str, re.Pattern]] = []

for canonical, aliases, default_unit in _LAB_PARAMS:
    alias_pattern = "|".join(re.escape(a) if "\\" not in a else a for a in aliases)
    pattern = re.compile(
        rf"(?:{alias_pattern})\s*[:\|]?\s*([\d]+\.?[\d]*)\s*({re.escape(default_unit)}|[a-zA-Z/%]+)?",
        re.IGNORECASE,
    )
    _LAB_PATTERNS.append((canonical, default_unit, pattern))



def _extract_date(text: str) -> str:
    patterns = [
        (r"\b(\d{4}-\d{2}-\d{2})\b",           "%Y-%m-%d"),
        (r"\b(\d{2}/\d{2}/\d{4})\b",           "%m/%d/%Y"),
        (r"\b(\d{2}-\d{2}-\d{4})\b",           "%d-%m-%Y"),
        (r"\b([A-Z][a-z]+\s+\d{1,2},?\s+\d{4})\b", "%B %d, %Y"),
    ]
    for pattern, fmt in patterns:
        m = re.search(pattern, text[:2000])
        if m:
            try:
                dt = datetime.strptime(m.group(1), fmt)
                return dt.replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass
    return datetime.now(timezone.utc).isoformat()



def _parse_tables(pdf) -> Optional[Dict[str, Dict]]:
    """
    Try to extract structured lab values from PDF tables.
    Returns a values dict or None if no usable tables found.

    Common lab report table format:
    | Test Name   | Result | Unit   | Reference Range |
    |-------------|--------|--------|-----------------|
    | WBC         | 15.2   | K/uL   | 4.5-11.0        |
    """
    values: Dict[str, Dict] = {}

    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if not table or len(table) < 2:
                continue
            header = [str(c).lower().strip() if c else "" for c in table[0]]
            name_col = val_col = unit_col = None
            for i, h in enumerate(header):
                if any(k in h for k in ["test", "parameter", "analyte", "name", "description"]):
                    name_col = i
                if any(k in h for k in ["result", "value", "reading"]):
                    val_col = i
                if any(k in h for k in ["unit", "uom", "measure"]):
                    unit_col = i

            if name_col is None or val_col is None:
                name_col, val_col = 0, 1
                unit_col = 2 if len(table[0]) > 2 else None

            for row in table[1:]:
                try:
                    name_raw = str(row[name_col] or "").strip()
                    val_raw  = str(row[val_col]  or "").strip()
                    unit_raw = str(row[unit_col] or "").strip() if unit_col and unit_col < len(row) else ""

                    canonical = None
                    for c, aliases, default_unit in _LAB_PARAMS:
                        if any(a.lower() in name_raw.lower() for a in aliases):
                            canonical = c
                            if not unit_raw:
                                unit_raw = default_unit
                            break
                    if not canonical:
                        continue

                    num_match = re.search(r"([\d]+\.?[\d]*)", val_raw)
                    if not num_match:
                        continue
                    numeric = float(num_match.group(1))
                    values[canonical] = {"value": round(numeric, 4), "unit": unit_raw}
                except Exception:
                    continue

    return values if values else None



def _parse_regex(text: str) -> Dict[str, Dict]:
    """Scan raw text for lab value patterns using compiled regex."""
    values: Dict[str, Dict] = {}
    for canonical, default_unit, pattern in _LAB_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                val = float(match.group(1))
                unit = match.group(2) or default_unit
                values[canonical] = {"value": round(val, 4), "unit": unit.strip()}
            except (ValueError, IndexError):
                continue
    return values



def parse(file_bytes: bytes, filename: str) -> Dict[str, Any]:
    """
    Parse a lab report PDF into a single ParseResult dict.

    Tries Strategy A (table extraction) first, falls back to Strategy B (regex).
    """
    warnings: List[str] = []
    raw_text = ""
    values: Dict[str, Dict] = {}
    strategy_used = "none"

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            table_values = _parse_tables(pdf)
            if table_values:
                values = table_values
                strategy_used = "table_extraction"

            text_parts = []
            for page in pdf.pages:
                t = page.extract_text(x_tolerance=2, y_tolerance=2)
                if t:
                    text_parts.append(t)
            raw_text = "\n".join(text_parts)

        if not values and raw_text:
            values = _parse_regex(raw_text)
            strategy_used = "regex_scan" if values else "none"
            if not values:
                warnings.append(
                    "No lab values found via table extraction or regex scan. "
                    "PDF may be scanned (image-only) or use an unrecognised format."
                )

    except Exception as exc:
        warnings.append(f"PDF parsing failed: {exc}")
        logger.error("pdf_lab_parser: error parsing '%s': %s", filename, exc)

    timestamp = _extract_date(raw_text) if raw_text else datetime.now(timezone.utc).isoformat()

    logger.info(
        "pdf_lab_parser: '%s'  strategy=%s, %d parameters extracted",
        filename, strategy_used, len(values),
    )

    return {
        "data_type":       "lab",
        "timestamp":       timestamp,
        "structured_json": {"values": values},
        "source_filename": filename,
        "rows_parsed":     1 if values else 0,
        "warnings":        warnings,
    }
