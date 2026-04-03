"""
api/routes/upload.py — File ingestion endpoint.

POST /upload/{patient_id}
  - Accepts: PDF, CSV, XLSX, TXT, JSON
  - Auto-detects file type (or uses caller's hint)
  - Stores raw file in Supabase Storage
  - Parses into structured JSON and inserts into parsed_data
  - Automatically triggers the agent pipeline as a BackgroundTask

Content-Type: multipart/form-data
Fields:
  file       : <binary>
  data_type  : "note" | "lab" | "vital" | "auto"  (default: "auto")
    trigger_analysis : true | false (default: true)
"""
from __future__ import annotations

import logging
import mimetypes
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import config
from agents.orchestrator import run_pipeline_queued
from database.storage_client import upload_file as storage_upload
from database.supabase_client import (
    get_parsed_data,
    get_patient,
    insert_parsed_data,
    insert_raw_data,
)
from processing.file_router import route as file_route

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────
# Response model
# ─────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    patient_id:          str
    filename:            str
    data_type_detected:  str
    rows_inserted:       int
    timestamps_detected: List[str]
    file_url:            Optional[str]
    warnings:            List[str]
    analysis_triggered:  bool
    message:             str


# ─────────────────────────────────────────────────────────
# Background task
# ─────────────────────────────────────────────────────────

async def _trigger_pipeline(patient_id: str, filename: str) -> None:
    """Run the full agent pipeline after successful upload."""
    try:
        report = await run_pipeline_queued(patient_id, reason=f"upload:{filename}")
        logger.info(
            "upload: auto-pipeline complete — patient=%s, file=%s, report_id=%s",
            patient_id, filename, report.get("_saved_report_id"),
        )
    except Exception as exc:
        logger.error(
            "upload: auto-pipeline FAILED — patient=%s, file=%s: %s",
            patient_id, filename, exc,
        )


# ─────────────────────────────────────────────────────────
# MIME type helper
# ─────────────────────────────────────────────────────────

def _content_type(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


# ─────────────────────────────────────────────────────────
# Upload endpoint
# ─────────────────────────────────────────────────────────

@router.post("/{patient_id}", response_model=UploadResponse)
async def upload_patient_file(
    patient_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    data_type: str = Form(default="auto"),
    trigger_analysis: bool = Form(default=False),
) -> UploadResponse:
    """
    Upload a clinical file for a patient.

    Supported formats:
      - PDF: clinical notes (text) or lab reports (tables/regex)
      - CSV / XLSX / XLS: lab results table (standard or MIMIC-III format)
      - TXT: plain clinical notes
      - JSON: pre-structured data (must include structured_json field)

    The agent pipeline is automatically triggered after successful upload.
    Use GET /reports/{patient_id}/current to retrieve the resulting report.
    """
    filename = file.filename or "upload"

    # ── 0. Validate patient_id format early ──────────────
    try:
        UUID(patient_id)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                "patient_id must be a valid UUID. "
                "Create a patient first via POST /patients and use that patient_id."
            ),
        )

    # ── 1. Validate data_type param ───────────────────────
    valid_types = {"note", "lab", "vital", "auto"}
    if data_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"data_type must be one of: {valid_types}. Got '{data_type}'.",
        )

    # ── 2. Validate patient exists ────────────────────────
    try:
        patient = get_patient(patient_id)
    except Exception as exc:
        logger.error("upload: patient lookup failed for '%s': %s", patient_id, exc)
        raise HTTPException(status_code=500, detail=f"Patient lookup failed: {exc}")
    if not patient:
        raise HTTPException(
            status_code=404,
            detail=f"Patient '{patient_id}' not found. Create the patient first.",
        )

    # ── 3. Read file bytes ────────────────────────────────
    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {exc}")

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    logger.info(
        "upload: received '%s' (%d bytes, hint=%s) for patient=%s",
        filename, len(file_bytes), data_type, patient_id,
    )

    # ── 4. Store raw file in Supabase Storage ────────────
    file_url = None
    if config.STORAGE_UPLOAD_ENABLED:
        file_url = storage_upload(
            patient_id=patient_id,
            filename=filename,
            file_bytes=file_bytes,
            content_type=_content_type(filename),
        )

    # ── 5. Parse file → list of ParseResults ─────────────
    all_warnings: List[str] = []
    parse_results = []
    try:
        parse_results = file_route(file_bytes, filename, hint=data_type)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc))
    except Exception as exc:
        logger.error("upload: parsing failed for '%s': %s", filename, exc)
        raise HTTPException(status_code=500, detail=f"File parsing error: {exc}")

    # ── 6. Insert raw_data metadata ───────────────────────
    try:
        insert_raw_data(
            patient_id=patient_id,
            data_type=parse_results[0]["data_type"] if parse_results else data_type,
            file_url=file_url or "",
            raw_content=None,  # raw bytes not stored as text — use Storage URL
        )
    except Exception as exc:
        logger.warning("upload: insert_raw_data failed (non-fatal): %s", exc)

    # ── 7. Insert each ParseResult into parsed_data ───────
    rows_inserted = 0
    timestamps: List[str] = []

    for result in parse_results:
        try:
            insert_parsed_data(
                patient_id=patient_id,
                data_type=result["data_type"],
                timestamp=result["timestamp"],
                structured_json=result["structured_json"],
            )
            rows_inserted += 1
            timestamps.append(result["timestamp"])
        except Exception as exc:
            logger.error("upload: insert_parsed_data failed: %s", exc)
            all_warnings.append(f"Row insert failed: {exc}")

        all_warnings.extend(result.get("warnings", []))

    logger.info(
        "upload: inserted %d/%d row(s) for patient=%s from '%s'",
        rows_inserted, len(parse_results), patient_id, filename,
    )

    # ── 8. Optionally trigger pipeline after upload ───────
    existing_context_rows = 0
    if rows_inserted == 0 and trigger_analysis:
        try:
            existing_context_rows = len(get_parsed_data(patient_id))
        except Exception as exc:
            logger.warning("upload: parsed_data lookup failed (non-fatal): %s", exc)

    if rows_inserted > 0 and trigger_analysis:
        background_tasks.add_task(_trigger_pipeline, patient_id, filename)
        analysis_triggered = True
        message = (
            f"Uploaded and parsed '{filename}' — {rows_inserted} row(s) stored. "
            "Agent pipeline triggered. Poll GET /reports/{patient_id}/current for results."
        )
    elif rows_inserted == 0 and trigger_analysis and existing_context_rows > 0:
        background_tasks.add_task(_trigger_pipeline, patient_id, filename)
        analysis_triggered = True
        message = (
            f"File '{filename}' produced no new rows, but existing context is available "
            f"({existing_context_rows} row(s)). Re-analysis triggered. "
            "Poll GET /reports/{patient_id}/current for results."
        )
    elif rows_inserted > 0:
        analysis_triggered = False
        message = (
            f"Uploaded and parsed '{filename}' — {rows_inserted} row(s) stored. "
            "Analysis deferred. Call POST /reports/analyse when all files are uploaded."
        )
    else:
        analysis_triggered = False
        message = f"File '{filename}' was parsed but no data rows were extracted. Check warnings."

    detected_type = parse_results[0]["data_type"] if parse_results else data_type

    return UploadResponse(
        patient_id=patient_id,
        filename=filename,
        data_type_detected=detected_type,
        rows_inserted=rows_inserted,
        timestamps_detected=timestamps,
        file_url=file_url,
        warnings=all_warnings,
        analysis_triggered=analysis_triggered,
        message=message,
    )
