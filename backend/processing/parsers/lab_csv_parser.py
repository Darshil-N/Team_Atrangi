"""
processing/parsers/lab_csv_parser.py  Parse tabular lab data from CSV/Excel.

Handles two modes:
  1. Standard mode: human-readable column headers (WBC, Lactate, etc.)
  2. MIMIC-III mode: auto-detected from itemid/valuenum/valueuom columns

Returns one ParseResult per data row (one per timestamp).
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


_PARAM_MAP: Dict[str, str] = {
    "wbc": "WBC", "white blood cell": "WBC", "white blood cells": "WBC",
    "leucocytes": "WBC", "leukocytes": "WBC",
    "hgb": "Hemoglobin", "hemoglobin": "Hemoglobin", "haemoglobin": "Hemoglobin",
    "hb": "Hemoglobin", "hgb (g/dl)": "Hemoglobin",
    "plt": "Platelets", "platelets": "Platelets", "platelet count": "Platelets",
    "thrombocytes": "Platelets",
    "lac": "Lactate", "lactate": "Lactate", "lactic acid": "Lactate",
    "lac (mmol/l)": "Lactate",
    "cr": "Creatinine", "creatinine": "Creatinine", "creat": "Creatinine",
    "creatinine (mg/dl)": "Creatinine",
    "bun": "BUN", "urea nitrogen": "BUN", "blood urea nitrogen": "BUN",
    "k": "Potassium", "k+": "Potassium", "potassium": "Potassium",
    "serum potassium": "Potassium",
    "na": "Sodium", "na+": "Sodium", "sodium": "Sodium", "serum sodium": "Sodium",
    "glu": "Glucose", "glucose": "Glucose", "blood glucose": "Glucose",
    "gluc": "Glucose",
    "ph": "pH", "arterial ph": "pH",
    "hco3": "Bicarbonate", "bicarbonate": "Bicarbonate", "bicarb": "Bicarbonate",
    "tbili": "Bilirubin", "bilirubin": "Bilirubin", "total bilirubin": "Bilirubin",
    "crp": "CRP", "c-reactive protein": "CRP",
    "pct": "Procalcitonin", "procalcitonin": "Procalcitonin",
    "trop": "Troponin", "troponin": "Troponin", "troponin i": "Troponin",
    "inr": "INR", "pt inr": "INR",
    "fio2": "FiO2", "pao2": "PaO2", "spo2": "SpO2",
}


_MIMIC_ITEMID_MAP: Dict[int, Tuple[str, str]] = {
    51300: ("WBC",          "K/uL"),
    51301: ("WBC",          "K/uL"),
    51222: ("Hemoglobin",   "g/dL"),
    51265: ("Platelets",    "K/uL"),
    50813: ("Lactate",      "mmol/L"),
    50912: ("Creatinine",   "mg/dL"),
    51006: ("BUN",          "mg/dL"),
    50971: ("Potassium",    "mmol/L"),
    50983: ("Sodium",       "mmol/L"),
    50931: ("Glucose",      "mg/dL"),
    50820: ("pH",           ""),
    50882: ("Bicarbonate",  "mmol/L"),
    50885: ("Bilirubin",    "mg/dL"),
    51237: ("INR",          ""),
    50821: ("PaO2",         "mmHg"),
    50816: ("FiO2",         "%"),
    220045: ("HeartRate",   "bpm"),
    220050: ("SysBP",       "mmHg"),
    220051: ("DiasBP",      "mmHg"),
    220052: ("MeanBP",      "mmHg"),
    220210: ("RespRate",    "/min"),
    223761: ("TempF",       "F"),
    220277: ("SpO2",        "%"),
}


_TS_COLUMNS = [
    "timestamp", "datetime", "date", "date_time",
    "collection_time", "result_date", "sample_date",
    "charttime", "chartdate",          # MIMIC-III
    "lab_date", "specimen_date", "order_date",
]


def _find_timestamp_column(df: pd.DataFrame) -> Optional[str]:
    """Return the first column name that looks like a timestamp."""
    lower_cols = {c.lower().replace(" ", "_"): c for c in df.columns}
    for candidate in _TS_COLUMNS:
        if candidate in lower_cols:
            return lower_cols[candidate]
    return None


def _parse_timestamp(value: Any) -> str:
    """Convert a timestamp value to ISO 8601 UTC string."""
    if pd.isna(value):
        return datetime.now(timezone.utc).isoformat()
    try:
        ts = pd.to_datetime(value, utc=True)
        return ts.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()



def _is_mimic_format(df: pd.DataFrame) -> bool:
    """Detect MIMIC-III format by checking for itemid + valuenum columns."""
    lower = [c.lower() for c in df.columns]
    return "itemid" in lower and "valuenum" in lower


def _parse_mimic(df: pd.DataFrame, filename: str) -> List[Dict[str, Any]]:
    """
    Parse MIMIC-III labevents/chartevents CSV format.

    Columns: SUBJECT_ID, HADM_ID, ITEMID, CHARTTIME, VALUE, VALUENUM, VALUEUOM
    Groups rows by CHARTTIME, building one ParseResult per timestamp.
    """
    warnings: List[str] = []

    df.columns = [c.lower() for c in df.columns]

    ts_col = "charttime" if "charttime" in df.columns else "chartdate"
    if ts_col not in df.columns:
        ts_col = None

    df["itemid"] = pd.to_numeric(df["itemid"], errors="coerce")
    known_mask = df["itemid"].isin(_MIMIC_ITEMID_MAP.keys())
    unknown_count = (~known_mask).sum()
    if unknown_count > 0:
        warnings.append(f"Skipped {unknown_count} rows with unrecognised MIMIC itemids.")
    df = df[known_mask].copy()

    if df.empty:
        warnings.append("No recognised MIMIC-III lab parameters found in this file.")
        return [{
            "data_type": "lab", "timestamp": datetime.now(timezone.utc).isoformat(),
            "structured_json": {"values": {}}, "source_filename": filename,
            "rows_parsed": 0, "warnings": warnings,
        }]

    df["valuenum"] = pd.to_numeric(df["valuenum"], errors="coerce")

    if ts_col:
        df["_ts"] = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    else:
        df["_ts"] = datetime.now(timezone.utc)

    results = []
    for ts_val, group in df.groupby("_ts"):
        values: Dict[str, Dict] = {}
        for _, row in group.iterrows():
            item_id = int(row["itemid"])
            if item_id not in _MIMIC_ITEMID_MAP:
                continue
            param_name, default_unit = _MIMIC_ITEMID_MAP[item_id]
            val = row["valuenum"]
            if pd.notna(val):
                unit = str(row.get("valueuom", default_unit) or default_unit)
                values[param_name] = {"value": round(float(val), 4), "unit": unit}

        if values:
            results.append({
                "data_type":       "lab",
                "timestamp":       _parse_timestamp(ts_val),
                "structured_json": {"values": values},
                "source_filename": filename,
                "rows_parsed":     1,
                "warnings":        [],
            })

    if not results:
        warnings.append("No valid numeric values found in MIMIC-III file.")
        results = [{
            "data_type": "lab", "timestamp": datetime.now(timezone.utc).isoformat(),
            "structured_json": {"values": {}}, "source_filename": filename,
            "rows_parsed": 0, "warnings": warnings,
        }]
    else:
        results[0]["warnings"].extend(warnings)

    logger.info("lab_csv_parser (MIMIC): parsed %d timestamp groups from '%s'", len(results), filename)
    return results



def _normalise_col(col: str) -> Optional[str]:
    """Map a column name to its canonical parameter name, or None if not recognised."""
    return _PARAM_MAP.get(col.lower().strip(), None)


def _parse_standard(df: pd.DataFrame, filename: str) -> List[Dict[str, Any]]:
    """
    Parse a standard lab CSV where each column is a parameter name.
    Each row = one timestamp's lab values.
    """
    warnings: List[str] = []
    ts_col = _find_timestamp_column(df)

    col_map: Dict[str, str] = {}
    for col in df.columns:
        if col == ts_col:
            continue
        canonical = _normalise_col(col)
        if canonical:
            col_map[col] = canonical
        else:
            warnings.append(f"Unrecognised column '{col}'  skipped.")

    if not col_map:
        warnings.append("No recognised lab parameter columns found.")

    results = []
    for idx, row in df.iterrows():
        timestamp = _parse_timestamp(row[ts_col]) if ts_col else datetime.now(timezone.utc).isoformat()
        values: Dict[str, Dict] = {}

        for raw_col, canonical in col_map.items():
            val = row.get(raw_col)
            try:
                numeric = float(val)
                values[canonical] = {"value": round(numeric, 4), "unit": ""}
            except (ValueError, TypeError):
                pass  # skip non-numeric cells silently

        if values:
            results.append({
                "data_type":       "lab",
                "timestamp":       timestamp,
                "structured_json": {"values": values},
                "source_filename": filename,
                "rows_parsed":     1,
                "warnings":        [],
            })

    if not results:
        warnings.append("No numeric data rows found.")
        results = [{
            "data_type": "lab", "timestamp": datetime.now(timezone.utc).isoformat(),
            "structured_json": {"values": {}}, "source_filename": filename,
            "rows_parsed": 0, "warnings": warnings,
        }]
    else:
        results[0]["warnings"].extend(warnings)

    logger.info("lab_csv_parser (standard): parsed %d row(s) from '%s'", len(results), filename)
    return results



def parse(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """
    Parse a CSV or Excel lab file into a list of ParseResult dicts.
    Auto-detects MIMIC-III format vs standard format.

    Returns one dict per timestamp row.
    """
    ext = filename.lower().split(".")[-1]

    try:
        if ext in ("xlsx", "xls"):
            df = pd.read_excel(io.BytesIO(file_bytes))
        else:
            for sep in (",", ";", "\t"):
                try:
                    df = pd.read_csv(io.BytesIO(file_bytes), sep=sep)
                    if len(df.columns) > 1:
                        break
                except Exception:
                    continue

        if df.empty:
            return [{
                "data_type": "lab", "timestamp": datetime.now(timezone.utc).isoformat(),
                "structured_json": {"values": {}}, "source_filename": filename,
                "rows_parsed": 0, "warnings": ["Empty file."],
            }]

        if _is_mimic_format(df):
            logger.info("lab_csv_parser: MIMIC-III format detected for '%s'", filename)
            return _parse_mimic(df, filename)
        else:
            return _parse_standard(df, filename)

    except Exception as exc:
        logger.error("lab_csv_parser: failed to parse '%s': %s", filename, exc)
        return [{
            "data_type": "lab", "timestamp": datetime.now(timezone.utc).isoformat(),
            "structured_json": {"values": {}}, "source_filename": filename,
            "rows_parsed": 0, "warnings": [f"Parse error: {exc}"],
        }]
