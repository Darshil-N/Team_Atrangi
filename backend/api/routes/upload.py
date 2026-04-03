"""
api/routes/upload.py — File upload endpoints.

Stub: returns 501 until Supabase Storage + background tasks are wired up (Part 2).
"""
from fastapi import APIRouter

router = APIRouter()


@router.post("/{patient_id}")
async def upload_files(patient_id: str):
    # TODO Part 2: accept multipart/form-data, upload to Supabase Storage,
    #              trigger background parsing task
    return {"detail": "Not implemented yet — coming in Part 2"}
