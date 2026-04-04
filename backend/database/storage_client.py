"""
database/storage_client.py  Upload raw patient files to Supabase Storage.

Bucket: hc01-patient-files
Path:   {patient_id}/{timestamp}_{filename}

If the upload fails, it logs a warning but does NOT crash the ingestion pipeline.
The raw file URL will be None in raw_data, but parsed_data still gets populated.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

BUCKET = "hc01-patient-files"


def _extract_public_url(url_resp: object) -> str:
    """Normalize Supabase get_public_url response across client versions."""
    if isinstance(url_resp, str):
        return url_resp

    if isinstance(url_resp, dict):
        data = url_resp.get("data")
        if isinstance(data, dict) and isinstance(data.get("publicUrl"), str):
            return data["publicUrl"]
        if isinstance(url_resp.get("publicUrl"), str):
            return url_resp["publicUrl"]

    return str(url_resp)


def upload_file(
    patient_id: str,
    filename: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
) -> Optional[str]:
    """
    Upload raw file bytes to Supabase Storage.

    Args:
        patient_id:   Patient UUID  used as the folder prefix.
        filename:     Original filename.
        file_bytes:   Raw file content.
        content_type: MIME type (e.g. "application/pdf", "text/csv").

    Returns:
        Public URL string if upload succeeded, None otherwise.
    """
    try:
        from database.supabase_client import get_client
        client = get_client()

        ts_slug = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        storage_path = f"{patient_id}/{ts_slug}_{filename}"

        client.storage.from_(BUCKET).upload(
            path=storage_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"},
        )

        url_resp = client.storage.from_(BUCKET).get_public_url(storage_path)
        public_url = _extract_public_url(url_resp)

        logger.info(
            "storage_client: uploaded '%s'  %s (%d bytes)",
            filename, storage_path, len(file_bytes),
        )
        return public_url

    except Exception as exc:
        logger.warning(
            "storage_client: upload FAILED for '%s'  %s. "
            "Continuing without file URL (parsed data still saved).",
            filename, exc,
        )
        return None


def get_file_url(patient_id: str, filename: str) -> Optional[str]:
    """
    Retrieve the public URL for a previously uploaded file.
    Returns None if not found.
    """
    try:
        from database.supabase_client import get_client
        client = get_client()
        files = client.storage.from_(BUCKET).list(patient_id)
        for f in files:
            if filename in f.get("name", ""):
                path = f"{patient_id}/{f['name']}"
                return _extract_public_url(client.storage.from_(BUCKET).get_public_url(path))
        return None
    except Exception as exc:
        logger.warning("storage_client.get_file_url failed: %s", exc)
        return None
