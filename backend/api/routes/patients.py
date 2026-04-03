"""
api/routes/patients.py — Patient CRUD endpoints.

Stub: returns 501 until database/supabase_client.py is wired up (Part 2).
"""
from fastapi import APIRouter

router = APIRouter()


@router.post("/")
async def create_patient():
    # TODO Part 2: wire to supabase_client + generate UUID + NFC URL
    return {"detail": "Not implemented yet — coming in Part 2"}


@router.get("/{patient_id}")
async def get_patient(patient_id: str):
    # TODO Part 2: fetch from Supabase patients table
    return {"detail": "Not implemented yet — coming in Part 2"}
