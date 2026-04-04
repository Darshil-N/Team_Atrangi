"""
api/routes/reports.py  Report retrieval and analysis trigger endpoints.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from agents.orchestrator import run_pipeline_queued
from database.supabase_client import get_current_report

logger = logging.getLogger(__name__)
router = APIRouter()



class AnalyseRequest(BaseModel):
    patient_id: str


class AnalyseResponse(BaseModel):
    patient_id: str
    status: str
    message: str



async def _run_pipeline_task(patient_id: str) -> None:
    """Async wrapper so FastAPI BackgroundTasks can schedule the pipeline."""
    try:
        report = await run_pipeline_queued(patient_id, reason="reports.analyse")
        logger.info(
            "Background pipeline complete  patient=%s, report_id=%s",
            patient_id, report.get("_saved_report_id"),
        )
    except Exception as exc:
        logger.error("Background pipeline failed  patient=%s: %s", patient_id, exc)



@router.post("/analyse", response_model=AnalyseResponse)
async def trigger_analysis(
    request: AnalyseRequest,
    background_tasks: BackgroundTasks,
) -> AnalyseResponse:
    """
    Trigger the full agent pipeline for a patient.
    The pipeline runs in the background  use GET /reports/{patient_id}/current
    (or Supabase Realtime on the frontend) to retrieve the result.
    """
    patient_id = request.patient_id.strip()
    if not patient_id:
        raise HTTPException(status_code=422, detail="patient_id must not be empty.")

    background_tasks.add_task(_run_pipeline_task, patient_id)

    logger.info("Analysis triggered  patient=%s", patient_id)
    return AnalyseResponse(
        patient_id=patient_id,
        status="queued",
        message="Pipeline started. Poll GET /reports/{patient_id}/current for the result.",
    )


@router.get("/{patient_id}/current")
async def get_patient_report(patient_id: str) -> Dict[str, Any]:
    """
    Return the current (most recent) report for a patient.
    Returns 404 if no report has been generated yet.
    """
    try:
        report = get_current_report(patient_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"No report found for patient {patient_id}. Run /reports/analyse first.",
        )

    return report
