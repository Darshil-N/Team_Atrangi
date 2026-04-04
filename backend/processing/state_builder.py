"""
processing/state_builder.py  Assembles the unified patient state dict.

This is the single source of truth fed into all agents. It queries Supabase
for all parsed_data rows of a patient and organises them into a sorted
timeline with three lanes: notes, labs, and vitals.

Usage:
    from processing.state_builder import build_state
    state = build_state(patient_id="550e8400-...")
"""
from __future__ import annotations

from typing import Any, Dict, List

from database.supabase_client import get_parsed_data



TimelineEntry = Dict[str, Any]

PatientState = Dict[str, Any]



def build_state(patient_id: str) -> PatientState:
    """
    Fetch all parsed_data rows for a patient and assemble a unified
    state dict that every agent can consume.

    The returned dict has the shape:
    {
        "patient_id": str,
        "timeline": [                       # sorted by timestamp ASC
            {
                "timestamp": "ISO8601",
                "type": "lab" | "note" | "vital",
                "data": { ...structured_json... }
            },
            ...
        ],
        "notes":  [...],   # filtered subset  type == "note"
        "labs":   [...],   # filtered subset  type == "lab"
        "vitals": [...],   # filtered subset  type == "vital"
        "total_entries": int,
    }

    Raises:
        ValueError: if patient_id is empty.
        RuntimeError: if Supabase returns an unexpected response.
    """
    if not patient_id:
        raise ValueError("patient_id must not be empty.")

    rows: List[Dict[str, Any]] = get_parsed_data(patient_id)

    timeline: List[TimelineEntry] = []
    notes:    List[TimelineEntry] = []
    labs:     List[TimelineEntry] = []
    vitals:   List[TimelineEntry] = []

    for row in rows:
        entry: TimelineEntry = {
            "timestamp": row.get("timestamp", ""),
            "type":      row.get("data_type", "unknown"),
            "data":      row.get("structured_json", {}),
        }
        timeline.append(entry)

        data_type = entry["type"]
        if data_type == "note":
            notes.append(entry)
        elif data_type == "lab":
            labs.append(entry)
        elif data_type == "vital":
            vitals.append(entry)

    state: PatientState = {
        "patient_id":    patient_id,
        "timeline":      timeline,
        "notes":         notes,
        "labs":          labs,
        "vitals":        vitals,
        "total_entries": len(timeline),
    }

    return state



def get_last_n_lab_entries(state: PatientState, n: int = 7) -> List[TimelineEntry]:
    """
    Return the last *n* lab timeline entries (most recent first).
    Used by lab_mapper to compute rolling trends over the last week.
    """
    return list(reversed(state["labs"]))[:n]


def state_is_empty(state: PatientState) -> bool:
    """Return True if no data has been uploaded/parsed for this patient yet."""
    return state["total_entries"] == 0


def summarise_state(state: PatientState) -> str:
    """
    Return a short human-readable summary of what data is available.
    Useful for logging and the chief agent's context block.
    """
    return (
        f"Patient {state['patient_id']} | "
        f"{len(state['notes'])} note(s), "
        f"{len(state['labs'])} lab record(s), "
        f"{len(state['vitals'])} vital snapshot(s) | "
        f"Timeline: {state['total_entries']} total entries"
    )
