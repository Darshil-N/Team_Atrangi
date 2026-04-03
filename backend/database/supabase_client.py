"""
database/supabase_client.py — Singleton Supabase client + typed CRUD helpers.

Every agent and route that needs DB access imports from here.
Never create a supabase.create_client() elsewhere — use get_client() only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

import config


# ─────────────────────────────────────────────────────────
# Singleton client
# ─────────────────────────────────────────────────────────

_client: Optional[Client] = None


def get_client() -> Client:
    """
    Return the shared Supabase client, creating it on first call.
    Thread-safe for async usage — supabase-py's client is stateless per request.
    """
    global _client
    if _client is None:
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            raise RuntimeError(
                "Supabase credentials missing. "
                "Set SUPABASE_URL and SUPABASE_KEY in your .env file."
            )
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


# ─────────────────────────────────────────────────────────
# Patient helpers
# ─────────────────────────────────────────────────────────

def create_patient(name: str, subject_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Insert a new patient row and return the created record.

    Args:
        name:       Patient full name.
        subject_id: Optional MIMIC-III subject_id for dataset linking.

    Returns:
        The newly created patient row as a dict.
    """
    client = get_client()
    patient_id = str(uuid.uuid4())
    nfc_url = f"https://kaarigars-hc01.app/patient/{patient_id}"

    data = {
        "patient_id": patient_id,
        "name": name,
        "admission_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if subject_id:
        data["subject_id"] = subject_id

    response = client.table("patients").insert(data).execute()
    row = response.data[0]
    # Attach nfc_url in memory even if the column doesn't exist in the DB yet
    row.setdefault("nfc_url", nfc_url)
    return row


def get_patient(patient_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a patient row by UUID. Returns None if not found."""
    client = get_client()
    response = (
        client.table("patients")
        .select("*")
        .eq("patient_id", patient_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


# ─────────────────────────────────────────────────────────
# Raw data helpers (uploaded files metadata)
# ─────────────────────────────────────────────────────────

def insert_raw_data(
    patient_id: str,
    data_type: str,       # 'note' | 'lab' | 'vital'
    file_url: str,
    raw_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Store metadata for one uploaded file."""
    client = get_client()
    response = (
        client.table("raw_data")
        .insert({
            "patient_id": patient_id,
            "data_type": data_type,
            "file_url": file_url,
            "raw_content": raw_content or "",
        })
        .execute()
    )
    return response.data[0]


# ─────────────────────────────────────────────────────────
# Parsed data helpers (structured post-processing output)
# ─────────────────────────────────────────────────────────

def insert_parsed_data(
    patient_id: str,
    data_type: str,
    timestamp: str,          # ISO 8601 string
    structured_json: Dict[str, Any],
) -> Dict[str, Any]:
    """Store one parsed data record (lab row, note parse, vital snapshot)."""
    client = get_client()
    response = (
        client.table("parsed_data")
        .insert({
            "patient_id": patient_id,
            "data_type": data_type,
            "timestamp": timestamp,
            "structured_json": structured_json,
        })
        .execute()
    )
    return response.data[0]


def get_parsed_data(patient_id: str) -> List[Dict[str, Any]]:
    """
    Fetch all parsed data rows for a patient, ordered by timestamp ascending.
    This is the primary input to state_builder.build_state().
    """
    client = get_client()
    response = (
        client.table("parsed_data")
        .select("*")
        .eq("patient_id", patient_id)
        .order("timestamp", desc=False)
        .execute()
    )
    return response.data or []


# ─────────────────────────────────────────────────────────
# Report helpers
# ─────────────────────────────────────────────────────────

def get_current_report(patient_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the most recent report marked is_current=true.
    Returns None if this is the patient's first analysis run.
    """
    client = get_client()
    response = (
        client.table("reports")
        .select("*")
        .eq("patient_id", patient_id)
        .eq("is_current", True)
        .order("report_version", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def save_report(
    patient_id: str,
    timeline: List[Dict],
    risk_flags: List[Dict],
    outlier_alerts: List[Dict],
    diagnosis_updated: bool,
    reasoning: str,
) -> Dict[str, Any]:
    """
    Persist a new report with graceful column-missing fallback.
    Tries a full insert first; if PGRST204 (column not found), retries
    with a minimal payload so the report always saves.
    """
    import logging
    log = logging.getLogger(__name__)
    client = get_client()

    # Step 1: retire previous current report
    client.table("reports").update({"is_current": False}).eq(
        "patient_id", patient_id
    ).eq("is_current", True).execute()

    # Step 2: determine version
    version_resp = (
        client.table("reports")
        .select("report_version")
        .eq("patient_id", patient_id)
        .order("report_version", desc=True)
        .limit(1)
        .execute()
    )
    next_version = (version_resp.data[0]["report_version"] + 1) if version_resp.data else 1

    full_payload = {
        "patient_id":        patient_id,
        "report_version":    next_version,
        "disease_timeline":  timeline,
        "risk_flags":        risk_flags,
        "outlier_alerts":    outlier_alerts,
        "diagnosis_updated": diagnosis_updated,
        "reasoning":         reasoning,
        "is_current":        True,
    }

    # Step 3a: try full insert
    try:
        response = client.table("reports").insert(full_payload).execute()
        return response.data[0]
    except Exception as exc:
        if "PGRST204" not in str(exc):
            raise
        log.warning(
            "save_report: schema mismatch (%s). "
            "Falling back to minimal payload. Run ALTER TABLE migrations to fix.", exc
        )

    # Step 3b: minimal fallback — pack extras into outlier_alerts JSONB
    enriched = outlier_alerts + [{"_meta": {
        "diagnosis_updated": diagnosis_updated,
        "reasoning":         reasoning,
    }}]
    minimal = {
        "patient_id":       patient_id,
        "report_version":   next_version,
        "disease_timeline": timeline,
        "risk_flags":       risk_flags,
        "outlier_alerts":   enriched,
        "is_current":       True,
    }
    response = client.table("reports").insert(minimal).execute()
    row = response.data[0]
    row.setdefault("diagnosis_updated", diagnosis_updated)
    row.setdefault("reasoning", reasoning)
    return row
