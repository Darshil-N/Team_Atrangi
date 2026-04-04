"""
api/routes/patients.py  Patient CRUD endpoints.

Used by upload flow to validate patient existence before ingestion.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from api.models import PatientCreate
from database.supabase_client import create_patient as db_create_patient
from database.supabase_client import get_patient as db_get_patient

router = APIRouter()


@router.post("/")
async def create_patient(payload: PatientCreate) -> Dict[str, Any]:
    """Create a new patient row in Supabase."""
    try:
        return db_create_patient(name=payload.name.strip(), subject_id=payload.subject_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create patient: {exc}")


@router.get("/{patient_id}")
async def get_patient(patient_id: str) -> Dict[str, Any]:
    """Fetch one patient by UUID."""
    try:
        patient = db_get_patient(patient_id.strip())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to fetch patient: {exc}")

    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient '{patient_id}' not found.")

    return patient
