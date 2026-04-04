"""
agents/chief_agent.py  Agent 4: Chief Medical Synthesis Agent (Gemini).

Receives outputs from all three earlier agents + previous report,
then produces the final structured diagnostic report using Gemini 1.5 Flash.

THE SINGLE MOST IMPORTANT BEHAVIOUR of this agent:
    If any outlier_alerts exist with probability "impossible" or
    "extremely unlikely", the agent MUST set diagnosis_updated = False.

This is enforced at THREE levels:
  Level 1: The mega-prompt explicitly instructs Gemini.
  Level 2: Gemini's response is parsed and validated.
  Level 3: Python code overrides diagnosis_updated = True to False
           if outliers with those probabilities are present.
   Even if Gemini ignores the instructions, Level 3 catches it.

Usage:
    from agents.chief_agent import run
    result = await run(state, symptoms_output, lab_output, rag_output, prev_report)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import google.generativeai as genai

import config
from processing.state_builder import PatientState

logger = logging.getLogger(__name__)



ChiefAgentOutput = Dict[str, Any]
"""
Shape returned by run():
{
    "timeline": [
        {
            "date":     "2024-04-01",
            "event":    "Admission",
            "status":   "baseline",   # baseline | stable | deteriorating | critical
            "vitals":   {...} or None,
            "labs":     {...} or None,
            "symptoms": [...] or None,
        }, ...
    ],
    "risk_flags": [
        {
            "risk":       "Early Sepsis",
            "severity":   "HIGH",
            "evidence":   ["WBC rising 27%", "Lactate 2.8 mmol/L", ...],
            "guideline_citations": [
                {"source": "Sepsis-3", "text": "...", "confidence": 0.92}
            ],
            "recommended_action": "Consider blood cultures...",
        }, ...
    ],
    "outlier_alerts": [
        {
            "parameter":             "Potassium",
            "reported_value":        14.0,
            "expected_range":        "3.5-5.0 mmol/L",
            "statistical_deviation": "9.5 standard deviations",
            "flag":                  "PROBABLE LAB ERROR",
            "action_required":       "Do NOT alter diagnosis. Request confirmed redraw.",
            "diagnosis_updated":     false,
        }, ...
    ],
    "family_communication": {
        "english": "string",
        "regional_language": "string",
        "regional_language_name": "Hindi",
        "regional_language_code": "hi"
    },
    "diagnosis_updated": bool,
    "reasoning":         str,
}
"""

_BLOCK_UPDATE_PROBABILITIES = {"impossible", "extremely unlikely"}



def _get_gemini_model() -> genai.GenerativeModel:
    """Configure and return the Gemini model. Called once per run."""
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file."
        )
    genai.configure(api_key=config.GEMINI_API_KEY)
    return genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        generation_config=genai.GenerationConfig(
            temperature=0.1,          # near-deterministic for medical reporting
            response_mime_type="application/json",   # native JSON mode
        ),
    )



def _format_guidelines(rag_output: Dict[str, Any]) -> str:
    """Format RAG citations into a compact block for the prompt."""
    guidelines = rag_output.get("guidelines", [])
    if not guidelines:
        return "No relevant guidelines retrieved."
    lines = []
    for g in guidelines[:5]:   # cap at 5 to control token usage
        lines.append(
            f'  [{g["title"]} p.{g["source_page"]}] '
            f'(relevance: {g["relevance_score"]:.2f})\n'
            f'  "{g["citation"][:300]}"'
        )
    return "\n\n".join(lines)


def _format_outliers_for_prompt(lab_output: Dict[str, Any]) -> str:
    """Summarise detected outliers for the chief prompt."""
    outliers = lab_output.get("outliers", [])
    if not outliers:
        return "None."
    lines = []
    for o in outliers:
        lines.append(
            f"   {o['parameter']}: {o['value']} "
            f"(expected {o['expected_range']})  "
            f"{o['statistical_deviation']}, probability: {o['probability']}"
        )
    return "\n".join(lines)


def _build_mega_prompt(
    state: PatientState,
    symptoms_output: Dict[str, Any],
    lab_output: Dict[str, Any],
    rag_output: Dict[str, Any],
    prev_report: Optional[Dict[str, Any]],
) -> str:
    """
    Build the mega-prompt that drives the chief synthesis.
    Keep it under ~6000 tokens to leave room for Gemini's JSON response.
    """
    timeline_str = json.dumps(state.get("timeline", [])[:20], indent=2)
    symptoms_str = json.dumps(symptoms_output.get("symptoms", []), indent=2)
    trends_str   = json.dumps(lab_output.get("trends", {}), indent=2)
    outliers_str = _format_outliers_for_prompt(lab_output)
    narrative_str = lab_output.get("narrative", "No narrative available.")
    guidelines_str = _format_guidelines(rag_output)
    prev_str = (
        json.dumps(prev_report, indent=2)[:2000]   # cap previous report at 2k chars
        if prev_report else
        "None  this is the first assessment for this patient."
    )

    return f"""You are a Chief Medical AI Synthesis Agent generating a structured diagnostic risk report for an ICU patient.

=== PATIENT TIMELINE (last 20 entries) ===
{timeline_str}

=== AGENT ANALYSIS ===
SYMPTOMS (from clinical notes):
{symptoms_str}

LAB TRENDS:
{trends_str}

LAB NARRATIVE:
{narrative_str}

=== STATISTICAL OUTLIER FLAGS ===
{outliers_str}

=== RELEVANT CLINICAL GUIDELINES ===
{guidelines_str}

=== PREVIOUS REPORT (for baseline comparison) ===
{prev_str}

=== CRITICAL INSTRUCTIONS  FOLLOW EXACTLY ===
1. OUTLIER REFUSAL (MANDATORY):
   - If ANY parameter is listed in the STATISTICAL OUTLIER FLAGS section above with probability "impossible" or "extremely unlikely", you MUST set "diagnosis_updated" to false.
   - Do NOT change the diagnosis severity or add new risk flags based on flagged outlier values.
   - Explain this in "reasoning"  cite the specific parameter and its deviation.

2. GUIDELINE CITATION:
   - Every risk flag MUST cite at least one guideline from the RELEVANT CLINICAL GUIDELINES section.
   - Use the exact title and a direct quote from the citation text.

3. PREVIOUS REPORT COMPARISON:
   - If a previous report exists, compare current trends to that baseline.
   - Prioritise guidelines over previous report if they conflict.

4. SAFETY:
   - This report is for DECISION SUPPORT ONLY, not clinical diagnosis.
   - Include this in "reasoning" if risk_flags are present.

5. FAMILY COMMUNICATION OUTPUT (MANDATORY):
    - Add a compassionate, jargon-free summary of the LAST 12 HOURS.
    - It must be understandable by a non-medical family member.
    - Provide two versions:
      a) english
      b) regional_language in {config.FAMILY_REGIONAL_LANGUAGE_NAME} ({config.FAMILY_REGIONAL_LANGUAGE_CODE})
    - If a blocking outlier exists, clearly explain that diagnosis is NOT being revised until redraw confirmation.

=== REQUIRED OUTPUT FORMAT (JSON ONLY  no markdown, no extra text) ===
{{
  "timeline": [
    {{
      "date": "YYYY-MM-DD",
      "event": "string",
      "status": "baseline|stable|deteriorating|critical",
      "vitals": {{}} or null,
      "labs": {{}} or null,
      "symptoms": [] or null
    }}
  ],
  "risk_flags": [
    {{
      "risk": "string",
      "severity": "LOW|MEDIUM|HIGH|CRITICAL",
      "evidence": ["string", ...],
      "guideline_citations": [
        {{"source": "string", "text": "string", "confidence": 0.0}}
      ],
      "recommended_action": "string"
    }}
  ],
  "outlier_alerts": [
    {{
      "parameter": "string",
      "reported_value": 0.0,
      "expected_range": "string",
      "statistical_deviation": "string",
      "flag": "PROBABLE LAB ERROR|VERIFY",
      "action_required": "string",
      "diagnosis_updated": false
    }}
  ],
    "family_communication": {{
    "english": "string",
    "regional_language": "string",
    "regional_language_name": "{config.FAMILY_REGIONAL_LANGUAGE_NAME}",
    "regional_language_code": "{config.FAMILY_REGIONAL_LANGUAGE_CODE}"
    }},
  "diagnosis_updated": true or false,
  "reasoning": "string"
}}"""


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    try:
        if not value:
            return None
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _build_family_communication(
    state: PatientState,
    report: Dict[str, Any],
    lab_output: Dict[str, Any],
) -> Dict[str, str]:
    """Build deterministic bilingual family-facing summary for the last 12 hours."""
    timeline: List[Dict[str, Any]] = state.get("timeline", []) or []
    latest_dt: Optional[datetime] = None
    for item in reversed(timeline):
        dt = _parse_iso_datetime(str(item.get("timestamp", "")))
        if dt is not None:
            latest_dt = dt
            break

    if latest_dt is None:
        last_12h = timeline[-6:]
    else:
        window_start = latest_dt - timedelta(hours=12)
        last_12h = []
        for item in timeline:
            dt = _parse_iso_datetime(str(item.get("timestamp", "")))
            if dt is None:
                continue
            if dt >= window_start:
                last_12h.append(item)

    risk_flags = report.get("risk_flags", []) or []
    blocking = [
        o for o in (lab_output.get("outliers", []) or [])
        if o.get("probability") in _BLOCK_UPDATE_PROBABILITIES
    ]

    if last_12h:
        last_status = str(last_12h[-1].get("type", "clinical")).lower()
        data_points = len(last_12h)
        english_intro = (
            f"Over the last 12 hours, we reviewed {data_points} recent updates, including {last_status} information."
        )
    else:
        english_intro = "Over the last 12 hours, we reviewed the latest available patient updates."

    if risk_flags:
        english_risk = (
            f"The AI has identified {len(risk_flags)} concern area(s) that the care team is monitoring closely."
        )
    else:
        english_risk = "Right now, there are no new major warning patterns from the latest data."

    if blocking:
        params = ", ".join(str(x.get("parameter", "lab value")) for x in blocking)
        english_guard = (
            f"One result ({params}) looks inconsistent with the last few days and may be mislabeled. "
            "For safety, diagnosis has NOT been changed until a confirmed redraw is received."
        )
    else:
        english_guard = "Current diagnosis decisions are based on consistent trends from the available data."

    english = f"{english_intro} {english_risk} {english_guard}"

    regional = (
        "Pichhle 12 ghanton ki jankari ko dhyan se dekha gaya hai. "
        "Care team patient ki sthiti par lagatar nazar rakhe hue hai. "
        + (
            "Ek naya lab result pichhle data se match nahin kar raha, isliye suraksha ke liye diagnosis tab tak update nahin kiya gaya hai jab tak redraw se pushti na ho jaye."
            if blocking
            else "Upalabdh data ke aadhaar par vartaman clinical faisle satark roop se liye ja rahe hain."
        )
    )

    return {
        "english": english,
        "regional_language": regional,
        "regional_language_name": config.FAMILY_REGIONAL_LANGUAGE_NAME,
        "regional_language_code": config.FAMILY_REGIONAL_LANGUAGE_CODE,
    }



def _extract_json(raw: str) -> Dict[str, Any]:
    """Extract JSON from Gemini response, handling markdown fences."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from Gemini response: {raw[:300]}")


def _build_outlier_alerts_from_lab(lab_output: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert lab_mapper outliers into the report's outlier_alerts format.
    Used as the authoritative source  Gemini may add more but cannot remove these.
    """
    alerts = []
    for o in lab_output.get("outliers", []):
        prob = o.get("probability", "")
        alerts.append({
            "parameter":             o.get("parameter", "Unknown"),
            "reported_value":        o.get("value", 0.0),
            "expected_range":        o.get("expected_range", "unknown"),
            "statistical_deviation": o.get("statistical_deviation", "unknown"),
            "flag": (
                "PROBABLE LAB ERROR"
                if prob in _BLOCK_UPDATE_PROBABILITIES
                else "VERIFY"
            ),
            "action_required": (
                "Do NOT alter diagnosis. Request confirmed redraw."
                if prob in _BLOCK_UPDATE_PROBABILITIES
                else "Verify with repeat measurement."
            ),
            "diagnosis_updated": False,
        })
    return alerts



def _apply_outlier_guard(
    report: Dict[str, Any],
    lab_output: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Level 3 outlier enforcement.

    If any lab_mapper outlier has probability "impossible" or "extremely unlikely",
    force diagnosis_updated = False regardless of what Gemini returned.

    This is the final, non-negotiable safety catch.
    """
    blocking_outliers = [
        o for o in lab_output.get("outliers", [])
        if o.get("probability") in _BLOCK_UPDATE_PROBABILITIES
    ]

    if not blocking_outliers:
        return report   # nothing to enforce

    if report.get("diagnosis_updated") is True:
        params = ", ".join(o["parameter"] for o in blocking_outliers)
        logger.warning(
            "chief_agent: Level 3 guard triggered  forcing diagnosis_updated=False "
            "due to blocking outlier(s): %s", params
        )
        report["diagnosis_updated"] = False
        report["reasoning"] = (
            f"[AUTOMATED SAFETY OVERRIDE] Diagnosis update blocked by outlier guard. "
            f"Blocking parameter(s): {params}. "
            f"Original reasoning: {report.get('reasoning', '')}"
        )

    authoritative_alerts = _build_outlier_alerts_from_lab(lab_output)
    existing_params = {
        a.get("parameter") for a in report.get("outlier_alerts", [])
    }
    for alert in authoritative_alerts:
        if alert["parameter"] not in existing_params:
            logger.warning(
                "chief_agent: adding missing outlier alert for '%s' that Gemini dropped.",
                alert["parameter"],
            )
            report.setdefault("outlier_alerts", []).append(alert)

    for alert in report.get("outlier_alerts", []):
        if str(alert.get("flag", "")).upper() != "PROBABLE LAB ERROR":
            for outlier in blocking_outliers:
                if alert.get("parameter") == outlier.get("parameter"):
                    alert["flag"] = "PROBABLE LAB ERROR"
                    alert["action_required"] = "Do NOT alter diagnosis. Request confirmed redraw."
                    alert["diagnosis_updated"] = False
                    break

    return report



def _build_fallback_report(
    state: PatientState,
    lab_output: Dict[str, Any],
    error_msg: str,
) -> ChiefAgentOutput:
    """
    Minimal safe report returned when Gemini is unreachable or parse fails.
    Preserves outlier alerts from lab_mapper so Test Case C still works.
    """
    return {
        "timeline":          [],
        "risk_flags":        [],
        "outlier_alerts":    _build_outlier_alerts_from_lab(lab_output),
        "family_communication": _build_family_communication(state, {"risk_flags": []}, lab_output),
        "diagnosis_updated": False,
        "reasoning": (
            f"Chief synthesis agent unavailable ({error_msg}). "
            "Outlier alerts from statistical analysis are preserved. "
            "Manual clinical assessment required."
        ),
    }



async def run(
    state: PatientState,
    symptoms_output: Dict[str, Any],
    lab_output: Dict[str, Any],
    rag_output: Dict[str, Any],
    prev_report: Optional[Dict[str, Any]] = None,
) -> ChiefAgentOutput:
    """
    Run the chief synthesis agent.

    Args:
        state:           Unified patient state from state_builder.
        symptoms_output: Output from note_parser.run().
        lab_output:      Output from lab_mapper.run().
        rag_output:      Output from rag_agent.run().
        prev_report:     Previous Supabase report row, or None.

    Returns:
        ChiefAgentOutput  the final structured diagnostic report.
    """
    patient_id: str = state.get("patient_id", "unknown")
    logger.info("chief_agent: starting  patient=%s", patient_id)

    try:
        prompt = _build_mega_prompt(
            state, symptoms_output, lab_output, rag_output, prev_report
        )
        model    = _get_gemini_model()
        response = model.generate_content(prompt)
        raw_text = response.text

        logger.debug("chief_agent: raw Gemini response (%d chars)", len(raw_text))

    except Exception as exc:
        msg = f"chief_agent: Gemini API call failed: {exc}"
        logger.error(msg)
        return _build_fallback_report(state, lab_output, str(exc))

    try:
        report = _extract_json(raw_text)
    except ValueError as exc:
        msg = f"chief_agent: JSON parse failed: {exc}"
        logger.error(msg)
        return _build_fallback_report(state, lab_output, str(exc))

    report = _apply_outlier_guard(report, lab_output)

    fc = report.get("family_communication")
    if not isinstance(fc, dict) or not fc.get("english") or not fc.get("regional_language"):
        report["family_communication"] = _build_family_communication(state, report, lab_output)
    else:
        report["family_communication"].setdefault("regional_language_name", config.FAMILY_REGIONAL_LANGUAGE_NAME)
        report["family_communication"].setdefault("regional_language_code", config.FAMILY_REGIONAL_LANGUAGE_CODE)

    logger.info(
        "chief_agent: done  patient=%s, risk_flags=%d, outlier_alerts=%d, diagnosis_updated=%s",
        patient_id,
        len(report.get("risk_flags", [])),
        len(report.get("outlier_alerts", [])),
        report.get("diagnosis_updated"),
    )

    return report
