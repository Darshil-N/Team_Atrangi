"""
agents/note_parser.py  Agent 1: Clinical Note Symptom Extractor.

Uses Ollama (phi3:mini) to parse unstructured clinical notes and extract
structured symptom data. Runs locally  no cloud API call needed.

VRAM safety:
  - num_ctx=4096   caps KV cache; prevents overflow on 6GB RTX 3050
  - num_gpu=99     all layers on GPU, zero RAM offload
  - temperature=0  deterministic JSON output every time

Usage:
    from agents.note_parser import run
    result = await run(state)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List

from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate

import config
from processing.state_builder import PatientState, TimelineEntry

logger = logging.getLogger(__name__)



NoteParserOutput = Dict[str, Any]
"""
Shape returned by run():
{
    "symptoms": [
        {
            "text":               "fever",
            "severity":           "moderate",     # mild | moderate | severe
            "mentioned_timestamp": "2024-04-01T06:00:00Z"
        },
        ...
    ],
    "total_notes_processed": int,
    "warnings": []   # non-fatal issues (e.g. one note failed JSON parse)
}
"""



_PROMPT_TEMPLATE = PromptTemplate(
    input_variables=["note_text", "note_timestamp"],
    template="""You are a clinical NLP system. Extract symptoms from the clinical note below.

CLINICAL NOTE (recorded at {note_timestamp}):
{note_text}

INSTRUCTIONS:
- Return ONLY a valid JSON object  no markdown, no explanation, no extra text.
- If no symptoms are mentioned, return an empty symptoms array.
- Use only the keys shown below.

REQUIRED OUTPUT FORMAT:
{{
  "symptoms": [
    {{
      "text": "<symptom name in lowercase>",
      "severity": "<mild|moderate|severe>",
      "mentioned_timestamp": "{note_timestamp}"
    }}
  ]
}}"""
)



def _build_llm() -> OllamaLLM:
    """
    Build the Ollama LLM instance with VRAM-safe parameters.
    Called once and reused  model stays loaded in GPU memory between calls.
    """
    return OllamaLLM(
        base_url=config.OLLAMA_HOST,
        model=config.OLLAMA_MODEL,
        num_ctx=config.OLLAMA_NUM_CTX,     # caps KV cache  stays within 6GB VRAM
        num_gpu=config.OLLAMA_NUM_GPU,     # all layers on GPU, no RAM spill
        temperature=0.0,                   # deterministic  structured output must be stable
        format="json",                     # Ollama-native JSON mode for phi3:mini
    )


_llm: OllamaLLM | None = None


def get_llm() -> OllamaLLM:
    """Return the shared LLM instance, creating it on first call."""
    global _llm
    if _llm is None:
        _llm = _build_llm()
    return _llm



def _extract_json(raw: str) -> Dict[str, Any]:
    """
    Robustly pull a JSON object out of the model's raw output.

    phi3:mini sometimes wraps the JSON in markdown fences even in JSON mode.
    This handles:
      - Clean JSON   : {"symptoms": [...]}
      - Fenced JSON  : ```json\n{...}\n```
      - Partial JSON : finds first { ... } block
    """
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

    logger.warning("note_parser: could not parse JSON from model output: %s", raw[:200])
    return {"symptoms": []}



def _process_one_note(entry: TimelineEntry, llm: OllamaLLM) -> List[Dict[str, Any]]:
    """
    Run the LLM on a single note timeline entry.
    Returns the list of extracted symptoms, or [] on failure.
    """
    note_text = ""
    data = entry.get("data", {})

    if isinstance(data, str):
        note_text = data
    elif isinstance(data, dict):
        note_text = (
            data.get("text")
            or data.get("content")
            or data.get("raw_text")
            or data.get("markdown")
            or json.dumps(data)   # last resort: dump the whole dict
        )

    if not note_text or not note_text.strip():
        logger.debug("note_parser: skipping empty note entry at %s", entry.get("timestamp"))
        return []

    max_chars = 15_000
    if len(note_text) > max_chars:
        logger.warning(
            "note_parser: note at %s truncated from %d to %d chars to fit context window",
            entry.get("timestamp"), len(note_text), max_chars,
        )
        note_text = note_text[:max_chars] + "\n[...truncated...]"

    prompt = _PROMPT_TEMPLATE.format(
        note_text=note_text,
        note_timestamp=entry.get("timestamp", "unknown"),
    )

    raw_output = llm.invoke(prompt)
    parsed = _extract_json(raw_output)
    return parsed.get("symptoms", [])



async def run(state: PatientState) -> NoteParserOutput:
    """
    Process all clinical notes in the patient state and return aggregated symptoms.

    Args:
        state: The unified patient state dict from state_builder.build_state().

    Returns:
        NoteParserOutput dict with:
          - symptoms:               aggregated list across all notes
          - total_notes_processed:  how many note entries were processed
          - warnings:               list of non-fatal warning strings
    """
    notes: List[TimelineEntry] = state.get("notes", [])
    patient_id: str = state.get("patient_id", "unknown")

    logger.info(
        "note_parser: starting  patient=%s, notes=%d",
        patient_id, len(notes),
    )

    if not notes:
        logger.info("note_parser: no notes found for patient %s", patient_id)
        return {
            "symptoms": [],
            "total_notes_processed": 0,
            "warnings": ["No clinical notes found for this patient."],
        }

    llm = get_llm()
    all_symptoms: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for i, entry in enumerate(notes):
        try:
            symptoms = _process_one_note(entry, llm)
            all_symptoms.extend(symptoms)
            logger.debug(
                "note_parser: note %d/%d  %d symptom(s)",
                i + 1, len(notes), len(symptoms),
            )
        except Exception as exc:
            msg = f"note_parser: failed on note {i+1} at {entry.get('timestamp')}: {exc}"
            logger.warning(msg)
            warnings.append(msg)

    logger.info(
        "note_parser: done  patient=%s, total_symptoms=%d, warnings=%d",
        patient_id, len(all_symptoms), len(warnings),
    )

    return {
        "symptoms": all_symptoms,
        "total_notes_processed": len(notes),
        "warnings": warnings,
    }
