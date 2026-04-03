# Basic Frontend (Upload UI)

This is a minimal static frontend to test patient creation, multi-file upload, and final report retrieval.

## Run

1. Start backend first:
   - from backend folder: `python start.py`
2. Serve this frontend as static files:
   - from frontend folder: `python -m http.server 5173`
3. Open:
   - `http://localhost:5173`

## Flow

1. Enter API Base URL (default `http://localhost:8080`)
2. Create a patient
3. Upload one or more files for that patient (`txt`, `csv`, `xlsx`, `pdf`, `json`)

## Batch Upload + Final Report

1. Keep `Upload all files first, then generate one final report` checked.
2. Select multiple files and upload.
3. Click `Generate Final Report` once.
4. Click `Fetch Current Report` to view the generated report JSON.

The response panel shows API output directly.
