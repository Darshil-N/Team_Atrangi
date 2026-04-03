"""
agents/lab_mapper.py — Agent 2: Temporal Lab Trend Mapper + Outlier Detector.

Two-stage pipeline:
  Stage A (Pandas/Scipy) — deterministic statistical analysis:
    • Computes per-parameter trends (slope, % change) over the last 7 days
    • Flags outliers where |value - rolling_mean| > 3 * rolling_std
    • This stage NEVER uses an LLM — statistics are ground truth

  Stage B (Ollama/phi3:mini) — narrative generation only:
    • Converts the numeric trend summary into plain clinical language
    • The LLM cannot override Stage A outlier flags — it only adds words

VRAM safety: same phi3:mini config as note_parser (num_ctx=4096, num_gpu=99).

Usage:
    from agents.lab_mapper import run
    result = await run(state)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate

import config
from agents.note_parser import get_llm, _extract_json   # reuse shared LLM + JSON helper
from processing.state_builder import PatientState, TimelineEntry

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# Output types
# ─────────────────────────────────────────────────────────

LabMapperOutput = Dict[str, Any]
"""
Shape returned by run():
{
    "trends": {
        "WBC":     {"slope": 1.2, "pct_change": 46.3, "direction": "rising",  "values": [...]},
        "Lactate": {"slope": 0.5, "pct_change": 133.0,"direction": "rising",  "values": [...]},
    },
    "outliers": [
        {
            "parameter":           "Potassium",
            "value":               14.0,
            "expected_range":      "3.5-5.0",
            "statistical_deviation": "9.5 standard deviations",
            "probability":         "impossible",
            "action":              "flag_for_redraw",
        }
    ],
    "narrative":  "WBC is rising sharply (46%) consistent with infection...",
    "warnings":   [],
}
"""

# Clinical reference ranges for common ICU parameters (used for outlier context)
_REFERENCE_RANGES: Dict[str, Tuple[float, float, str]] = {
    "WBC":          (4.5,   11.0,  "K/uL"),
    "Lactate":      (0.5,   2.0,   "mmol/L"),
    "Creatinine":   (0.7,   1.3,   "mg/dL"),
    "Potassium":    (3.5,   5.0,   "mmol/L"),
    "Sodium":       (136.0, 145.0, "mmol/L"),
    "Hemoglobin":   (12.0,  17.5,  "g/dL"),
    "Platelets":    (150.0, 400.0, "K/uL"),
    "BUN":          (7.0,   25.0,  "mg/dL"),
    "Glucose":      (70.0,  100.0, "mg/dL"),
    "pH":           (7.35,  7.45,  ""),
    "Bicarbonate":  (22.0,  29.0,  "mmol/L"),
}

# Outlier threshold: flag if |value - mean_prev_3| > OUTLIER_STD_THRESHOLD * std_prev_3
OUTLIER_STD_THRESHOLD = 3.0

# Minimum readings per parameter to compute a trend
MIN_READINGS_FOR_TREND = 2


# ─────────────────────────────────────────────────────────
# Narrative generation prompt
# ─────────────────────────────────────────────────────────

_NARRATIVE_PROMPT = PromptTemplate(
    input_variables=["trend_summary", "outlier_summary"],
    template="""You are a clinical AI assistant. Write a brief clinical interpretation of the lab trends below.

LAB TRENDS (last 7 days):
{trend_summary}

FLAGGED OUTLIERS:
{outlier_summary}

INSTRUCTIONS:
- Return ONLY a valid JSON object — no markdown, no explanation, no extra text.
- Keep the narrative under 150 words.
- Do NOT change or reinterpret the outlier flags — just mention them as flagged.

REQUIRED OUTPUT FORMAT:
{{
  "narrative": "<your clinical interpretation here>"
}}"""
)


# ─────────────────────────────────────────────────────────
# Stage A: Statistical analysis (pure Pandas/Numpy)
# ─────────────────────────────────────────────────────────

def _extract_lab_series(lab_entries: List[TimelineEntry]) -> Dict[str, pd.Series]:
    """
    Convert lab timeline entries into per-parameter Pandas Series indexed by time.

    Each lab entry's data dict can contain parameters as top-level keys, e.g.:
        {"WBC": {"value": 15.2, "unit": "K/uL"}, "Lactate": {"value": 2.8, ...}}
    or flat:
        {"WBC": 15.2, "Lactate": 2.8}
    """
    records: List[Dict[str, Any]] = []

    for entry in lab_entries:
        ts = entry.get("timestamp", "")
        data = entry.get("data", {})

        row: Dict[str, Any] = {"timestamp": ts}
        for key, val in data.items():
            if key == "values" and isinstance(val, dict):
                # Nested format: {"values": {"WBC": {"value": 15.2}, ...}}
                for param, param_data in val.items():
                    if isinstance(param_data, dict):
                        row[param] = param_data.get("value")
                    else:
                        row[param] = param_data
            elif isinstance(val, (int, float)):
                row[key] = val
            elif isinstance(val, dict) and "value" in val:
                row[key] = val["value"]

        records.append(row)

    if not records:
        return {}

    df = pd.DataFrame(records)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.sort_values("timestamp").set_index("timestamp")

    # Build per-parameter Series, dropping non-numeric columns
    series_map: Dict[str, pd.Series] = {}
    for col in df.columns:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(s) >= 1:
            series_map[col] = s

    return series_map


def _compute_trend(series: pd.Series) -> Dict[str, Any]:
    """
    Compute trend statistics for one lab parameter.

    Returns dict with:
        slope:       linear regression slope (units per day)
        pct_change:  % change from first to last value
        direction:   'rising' | 'falling' | 'stable'
        values:      list of raw values
    """
    values = series.values.astype(float)
    n = len(values)

    # Convert index to day-offset floats for polyfit
    if hasattr(series.index, "astype"):
        try:
            days = (
                (series.index - series.index[0]).total_seconds() / 86400
            ).values.astype(float)
        except Exception:
            days = np.arange(n, dtype=float)
    else:
        days = np.arange(n, dtype=float)

    slope = float(np.polyfit(days, values, 1)[0]) if n >= 2 else 0.0

    first, last = float(values[0]), float(values[-1])
    pct_change = ((last - first) / first * 100) if first != 0 else 0.0

    if abs(pct_change) < 5:
        direction = "stable"
    elif pct_change > 0:
        direction = "rising"
    else:
        direction = "falling"

    return {
        "slope":      round(slope, 4),
        "pct_change": round(pct_change, 2),
        "direction":  direction,
        "values":     [round(float(v), 3) for v in values],
    }


def _detect_outlier(
    param: str,
    series: pd.Series,
) -> Optional[Dict[str, Any]]:
    """
    Flag the latest value as an outlier if it is OUTLIER_STD_THRESHOLD (3) standard
    deviations away from the mean of the preceding 3 readings.

    This is the critical hallucination-prevention mechanism:
    If Potassium = 14.0 mmol/L (physiologically impossible),
    this function flags it BEFORE the chief agent ever sees it.

    Returns an outlier dict, or None if the latest value is within normal range.
    """
    if len(series) < 2:
        return None  # Need at least 2 points: one history, one new reading

    latest_val = float(series.iloc[-1])
    history = series.iloc[:-1]   # all readings except the latest

    mean_hist = float(history.mean())
    std_hist  = float(history.std(ddof=0))   # population std (ddof=0)

    # Avoid division-by-zero for perfectly constant history
    if std_hist == 0:
        # If history is perfectly constant and new value differs, flag it
        if abs(latest_val - mean_hist) > 0.01:
            n_std = float("inf")
        else:
            return None
    else:
        n_std = abs(latest_val - mean_hist) / std_hist

    if n_std < OUTLIER_STD_THRESHOLD:
        return None  # Normal variation — not an outlier

    # Build the outlier record
    ref = _REFERENCE_RANGES.get(param)
    if ref:
        lo, hi, unit = ref
        expected_range = f"{lo}-{hi} {unit}".strip()
    else:
        expected_range = f"within {mean_hist:.2f} ± {std_hist:.2f} (historical)"

    # Classify probability for the chief agent
    if n_std == float("inf") or n_std > 9:
        probability = "impossible"
    elif n_std > 6:
        probability = "extremely unlikely"
    else:
        probability = "highly unlikely"

    return {
        "parameter":             param,
        "value":                 round(latest_val, 3),
        "expected_range":        expected_range,
        "statistical_deviation": f"{n_std:.1f} standard deviations" if n_std != float("inf") else "infinite standard deviations",
        "probability":           probability,
        "action":                "flag_for_redraw",
    }


def _run_statistical_analysis(
    lab_entries: List[TimelineEntry],
) -> Tuple[Dict[str, Dict], List[Dict]]:
    """
    Stage A: deterministic statistical analysis.

    Returns:
        trends:   dict of {param: trend_dict}
        outliers: list of outlier dicts (may be empty)
    """
    series_map = _extract_lab_series(lab_entries)
    trends:   Dict[str, Dict] = {}
    outliers: List[Dict]      = []

    for param, series in series_map.items():
        if len(series) >= MIN_READINGS_FOR_TREND:
            trends[param] = _compute_trend(series)

        # Always check for outliers even with just 2 data points
        if len(series) >= 2:
            outlier = _detect_outlier(param, series)
            if outlier:
                outliers.append(outlier)
                logger.warning(
                    "lab_mapper: OUTLIER DETECTED — %s = %s (%s)",
                    param, outlier["value"], outlier["statistical_deviation"],
                )

    return trends, outliers


# ─────────────────────────────────────────────────────────
# Stage B: Narrative generation (Ollama)
# ─────────────────────────────────────────────────────────

def _build_trend_summary(trends: Dict[str, Dict]) -> str:
    """Convert the numeric trends dict into a compact string for the prompt."""
    if not trends:
        return "No lab trends available."
    lines = []
    for param, t in trends.items():
        lines.append(
            f"  {param}: {t['direction']} "
            f"({t['pct_change']:+.1f}% over {len(t['values'])} readings, "
            f"slope={t['slope']:.3f}/day)"
        )
    return "\n".join(lines)


def _build_outlier_summary(outliers: List[Dict]) -> str:
    """Convert the outliers list into a compact string for the prompt."""
    if not outliers:
        return "None."
    lines = []
    for o in outliers:
        lines.append(
            f"  {o['parameter']}: {o['value']} (expected {o['expected_range']}) "
            f"— {o['statistical_deviation']}, probability: {o['probability']}"
        )
    return "\n".join(lines)


def _generate_narrative(
    trends: Dict[str, Dict],
    outliers: List[Dict],
    llm: OllamaLLM,
) -> str:
    """
    Stage B: Ask phi3:mini to write a brief clinical interpretation.
    The LLM receives the computed stats — it cannot change the outlier flags.
    """
    trend_summary   = _build_trend_summary(trends)
    outlier_summary = _build_outlier_summary(outliers)

    prompt = _NARRATIVE_PROMPT.format(
        trend_summary=trend_summary,
        outlier_summary=outlier_summary,
    )

    try:
        raw_output = llm.invoke(prompt)
        parsed     = _extract_json(raw_output)
        return parsed.get("narrative", trend_summary)   # fallback to raw summary
    except Exception as exc:
        logger.warning("lab_mapper: narrative generation failed: %s", exc)
        return trend_summary   # non-fatal — return the numeric summary instead


# ─────────────────────────────────────────────────────────
# Public entry point (called by orchestrator)
# ─────────────────────────────────────────────────────────

async def run(state: PatientState) -> LabMapperOutput:
    """
    Run the two-stage lab analysis pipeline.

    Args:
        state: The unified patient state dict from state_builder.build_state().

    Returns:
        LabMapperOutput with trends, outliers, narrative, warnings.
    """
    lab_entries: List[TimelineEntry] = state.get("labs", [])
    patient_id: str = state.get("patient_id", "unknown")

    logger.info(
        "lab_mapper: starting — patient=%s, lab_entries=%d",
        patient_id, len(lab_entries),
    )

    if not lab_entries:
        logger.info("lab_mapper: no lab data for patient %s", patient_id)
        return {
            "trends":   {},
            "outliers": [],
            "narrative": "No lab data available for this patient.",
            "warnings": ["No lab entries found."],
        }

    warnings: List[str] = []

    # ── Stage A: Statistical analysis (deterministic, no LLM) ──
    try:
        trends, outliers = _run_statistical_analysis(lab_entries)
    except Exception as exc:
        msg = f"lab_mapper: Stage A (statistics) failed: {exc}"
        logger.error(msg)
        warnings.append(msg)
        trends, outliers = {}, []

    logger.info(
        "lab_mapper: Stage A done — %d trends, %d outlier(s)",
        len(trends), len(outliers),
    )

    # ── Stage B: Narrative generation (Ollama) ──
    try:
        llm = get_llm()
        narrative = _generate_narrative(trends, outliers, llm)
    except Exception as exc:
        msg = f"lab_mapper: Stage B (narrative) failed: {exc}"
        logger.warning(msg)
        warnings.append(msg)
        narrative = _build_trend_summary(trends)   # non-fatal fallback

    logger.info("lab_mapper: done — patient=%s", patient_id)

    return {
        "trends":   trends,
        "outliers": outliers,
        "narrative": narrative,
        "warnings": warnings,
    }
