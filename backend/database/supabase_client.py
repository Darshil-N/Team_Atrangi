"""
database/supabase_client.py  Singleton Supabase client + typed CRUD helpers.

Every agent and route that needs DB access imports from here.
Never create a supabase.create_client() elsewhere  use get_client() only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

import config



_client: Optional[Client] = None
_reports_has_family_communication: Optional[bool] = None


def get_client() -> Client:
    """
    Return the shared Supabase client, creating it on first call.
    Thread-safe for async usage  supabase-py's client is stateless per request.
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



def insert_raw_data(
    patient_id: str,
    data_type: str,       # 'note' | 'lab' | 'vital'
    file_url: str,
    raw_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Store metadata for one uploaded file with schema fallback support."""
    client = get_client()

    payload = {
        "patient_id": patient_id,
        "data_type": data_type,
        "file_url": file_url,
        "raw_content": raw_content or "",
    }

    try:
        response = client.table("raw_data").insert(payload).execute()
        return response.data[0]
    except Exception as exc:
        if "PGRST204" not in str(exc):
            raise

    fallback_payload = {
        "patient_id": patient_id,
        "data_type": data_type,
        "file_path": file_url,
        "raw_content": raw_content or "",
    }
    response = client.table("raw_data").insert(fallback_payload).execute()
    return response.data[0]



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
    family_communication: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Persist a new report with graceful column-missing fallback.
    Tries a full insert first; if PGRST204 (column not found), retries
    with a minimal payload so the report always saves.
    """
    global _reports_has_family_communication

    import logging
    log = logging.getLogger(__name__)
    client = get_client()

    def _merge_timeline(existing: List[Dict], incoming: List[Dict]) -> List[Dict]:
        merged: List[Dict] = []
        seen = set()
        for row in (existing or []) + (incoming or []):
            marker = (
                row.get("date"),
                row.get("timestamp"),
                row.get("event"),
                row.get("status"),
            )
            if marker in seen:
                continue
            seen.add(marker)
            merged.append(row)
        return merged

    current_report = get_current_report(patient_id)
    next_version = (int(current_report["report_version"]) + 1) if current_report else 1

    merged_timeline = _merge_timeline(
        current_report.get("disease_timeline", []) if current_report else [],
        timeline,
    )
    merged_risk_flags = risk_flags if risk_flags else (current_report.get("risk_flags", []) if current_report else [])
    merged_outliers = outlier_alerts if outlier_alerts else (current_report.get("outlier_alerts", []) if current_report else [])
    merged_reasoning = reasoning or (current_report.get("reasoning", "") if current_report else "")
    merged_diagnosis_updated = diagnosis_updated if diagnosis_updated is not None else bool(
        current_report.get("diagnosis_updated", False) if current_report else False
    )

    full_payload = {
        "patient_id":        patient_id,
        "report_version":    next_version,
        "disease_timeline":  merged_timeline,
        "risk_flags":        merged_risk_flags,
        "outlier_alerts":    merged_outliers,
        "diagnosis_updated": merged_diagnosis_updated,
        "reasoning":         merged_reasoning,
        "family_communication": family_communication or {},
        "is_current":        True,
    }

    base_payload = {k: v for k, v in full_payload.items() if k != "family_communication"}
    insert_payload = full_payload if _reports_has_family_communication is not False else base_payload

    if current_report:
        client.table("reports").update({"is_current": False}).eq("id", current_report["id"]).execute()

    try:
        response = client.table("reports").insert(insert_payload).execute()
        if _reports_has_family_communication is None:
            _reports_has_family_communication = True
        return response.data[0]
    except Exception as exc:
        error_text = str(exc)
        if "PGRST204" not in error_text:
            raise
        if "family_communication" in error_text:
            _reports_has_family_communication = False
            log.warning(
                "save_report: reports.family_communication missing (%s). "
                "Using compatibility payload until DB migration is applied.",
                exc,
            )
        else:
            log.warning(
                "save_report: schema mismatch (%s). "
                "Falling back to minimal payload. Run ALTER TABLE migrations to fix.",
                exc,
            )

    try:
        response = client.table("reports").insert(base_payload).execute()
        row = response.data[0]
        row.setdefault("family_communication", family_communication or {})
        return row
    except Exception:
        pass

    enriched = merged_outliers + [{"_meta": {
        "diagnosis_updated": merged_diagnosis_updated,
        "reasoning":         merged_reasoning,
        "family_communication": family_communication or {},
    }}]
    minimal = {
        "patient_id":       patient_id,
        "report_version":   next_version,
        "disease_timeline": merged_timeline,
        "risk_flags":       merged_risk_flags,
        "outlier_alerts":   enriched,
        "is_current":       True,
    }
    response = client.table("reports").insert(minimal).execute()
    row = response.data[0]
    row.setdefault("diagnosis_updated", diagnosis_updated)
    row.setdefault("reasoning", reasoning)
    return row
