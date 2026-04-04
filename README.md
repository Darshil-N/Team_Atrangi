<p align="center">
  <img src="./Logo.jpeg" alt="Sanjeevani Logo" width="170"/>
</p>

<h1 align="center">Sanjeevani - Diagnostic Risk Assistant</h1>

<p align="center">
  <strong>Architecture-first multi-agent ICU decision-support platform</strong><br/>
  Team Atrangi · HC01
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-blue?logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/Ollama-phi3:mini-black?logo=ollama"/>
  <img src="https://img.shields.io/badge/Gemini-2.5%20Flash-4285F4?logo=google&logoColor=white"/>
  <img src="https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white"/>
  <img src="https://img.shields.io/badge/ChromaDB-RAG-FF6B6B"/>
</p>

---

## 1. What Is New (Latest Features)

The README has been updated for the latest product behavior across frontend and backend.

- NFC secure link now supports doctor PIN verification and then shows:
  - full clinical report
  - disease progression timeline chart
  - analytics charts (latest labs, risk severity, ingested source mix)
- Multi-language analytics support in English, Hindi, and Marathi.
- Runtime translation pipeline in frontend for dynamic clinical text:
  - chunking and cache
  - medical-term masking/unmasking
  - fallback to source text on translation failure
- Family communication cards show both English and configured regional language output.
- PIN-based role access with lockout/cooldown controls and session timeout.
- PDF clinical report export includes graph summaries and timeline trend chart.
- Real-time current-report updates using Supabase channels.

---

## 2. System Purpose

Sanjeevani is a multi-agent clinical decision-support system that ingests patient files (notes, labs, vitals), builds a unified temporal state, retrieves guideline evidence, and produces structured risk reports.

Core goals:

- Fast, explainable risk synthesis for ICU workflows.
- Refusal of unsafe diagnosis updates when statistically improbable outliers are detected.
- Deterministic and traceable ingestion-to-report pipeline.

This system is decision support software and does not replace clinician judgment.

---

## 3. Architecture Overview

### 3.1 High-level Diagram (Image)

<p align="center">
  <img src="./System_architecture.png" alt="Sanjeevani System Architecture Diagram" width="980"/>
</p>

### 3.2 High-level Diagram (Text)

```text
Frontend (React)                       Backend (FastAPI)
------------------                     -----------------------------
Staff / Doctor / Patient UI  --->      /upload, /reports, /patients
PIN + role gating                      API routes + orchestration
Realtime report views                  |
NFC secure access                      v
Translation + PDF export       Orchestrator (agents/orchestrator.py)
                               |-------------------------------|
                               | Parallel workers              |
                               |  - note_parser (local LLM)    |
                               |  - lab_mapper (stats + LLM)   |
                               |  - rag_agent (Chroma retriever)|
                               |-------------------------------|
                                              |
                                              v
                               chief_agent (Gemini synthesis + guards)
                                              |
                                              v
                               Supabase PostgreSQL (patients, parsed_data,
                               reports, security/audit tables)
```

---

## 4. Frontend Features

### 4.1 Portals and Access

- Single role-aware login flow for doctor, staff, patient.
- PIN authentication with failed-attempt handling and timed lockouts.
- 15-minute session inactivity timeout.
- Role-restricted navigation and route protection.

### 4.2 NFC Workflow

- NFC URL pattern: /nfc/:patientId
- Requires doctor identifier + doctor PIN verification.
- After successful verification, shows:
  - patient report content
  - trend/time chart card
  - integrated analytics charts in the same page

### 4.3 Analytics and Clinical Views

- Disease progression timeline graph from report timeline rows.
- Latest lab-value bars.
- Risk severity distribution chart.
- Ingested source breakdown chart.
- Family communication cards for English and regional language text.

### 4.4 Multilingual and Translation

- UI i18n dictionary for English/Hindi/Marathi labels.
- Runtime translation for dynamic text fields using external translation API.
- Translation chunking, in-memory caching, and failure fallback.
- Medical glossary masking to preserve key terms during translation.

### 4.5 Report Export

- PDF export includes visual summaries and timeline trend graphic.
- Structured sections for risk flags, outliers, timeline, and chief reasoning.

---

## 5. Backend Features

### 5.1 API Layer

- Patient CRUD-oriented retrieval and creation endpoints.
- Upload parsing endpoint for notes/labs/vitals.
- Report analysis trigger and current report fetch.
- Health endpoint for operational checks.

### 5.2 Agent Pipeline

- note_parser: symptom signal extraction.
- lab_mapper: trend computation and outlier statistics.
- rag_agent: guideline retrieval from vector store.
- chief_agent: report synthesis + safety policy enforcement.

### 5.3 Safety Guardrails

- Three-level outlier refusal strategy:
  - statistical outlier detection
  - explicit synthesis constraints
  - hard post-generation override
- If blocking outliers are present, diagnosis update is forced false.

### 5.4 Family Communication Output

- Report contains family_communication with:
  - english
  - regional_language
  - regional_language_name
  - regional_language_code
- Regional language defaults are configurable via environment variables.

---

## 6. End-to-End Data Flow

1. Staff uploads clinical file.
2. Backend parses and stores structured rows in parsed_data.
3. Analysis pipeline runs (orchestrator + agents).
4. Chief report is generated with outlier safety checks.
5. Report is versioned; latest is marked is_current=true.
6. Frontend renders diagnostics, analytics, family communication, and export views.
7. NFC secure flow allows doctor-verified access to the same patient intelligence.

---

## 7. Technology Stack

| Layer | Technology |
|---|---|
| Frontend | React, Vite, Recharts, html2pdf |
| API | FastAPI, Uvicorn |
| Local Model Runtime | Ollama (phi3:mini) |
| Cloud Synthesis | Gemini 2.5 Flash |
| Vector Retrieval | ChromaDB + sentence-transformers |
| Database | Supabase PostgreSQL |
| Data Processing | Pandas, NumPy, PDF parsers |

---

## 8. Repository Structure

```text
Team_Atrangi/
├── backend/
│   ├── api/
│   ├── agents/
│   ├── database/
│   ├── processing/
│   ├── vector_db/
│   ├── config.py
│   ├── requirements.txt
│   └── start.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── styles.css
│   │   └── lib/
│   └── package.json
├── schema.sql
├── Logo.jpeg
└── System_architecture.png
```

---

## 9. Quick Start

### 9.1 Backend

```bash
cd backend
pip install -r requirements.txt
python start.py
```

Backend docs: http://localhost:8080/docs

### 9.2 Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## 10. Required Environment Variables

### 10.1 Backend (.env)

- SUPABASE_URL
- SUPABASE_KEY
- GEMINI_API_KEY
- GEMINI_MODEL
- OLLAMA_HOST
- OLLAMA_MODEL
- CHIEF_PROVIDER
- CHIEF_ALLOW_GEMINI_FALLBACK
- STORAGE_UPLOAD_ENABLED
- FAMILY_REGIONAL_LANGUAGE_NAME
- FAMILY_REGIONAL_LANGUAGE_CODE

### 10.2 Frontend (.env)

- VITE_SUPABASE_URL
- VITE_SUPABASE_ANON_KEY
- VITE_BACKEND_URL
- VITE_PUBLIC_APP_URL

---

## 11. Key Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | /health | Service health and runtime config view |
| POST | /patients/ | Create patient record |
| GET | /patients/{patient_id} | Read patient metadata |
| POST | /upload/{patient_id} | Upload and parse clinical file |
| POST | /reports/analyse | Trigger analysis pipeline |
| GET | /reports/{patient_id}/current | Fetch current report |

---

## 12. Operational Notes

- Apply backend/database/security_schema.sql in Supabase before using PIN/audit flows.
- Keep STORAGE_UPLOAD_ENABLED=false for DB-first operation when object storage is not needed.
- Large frontend chunk warnings are optimization notes, not hard build failures.

---

<p align="center">
  <em>Sanjeevani - reliable, explainable ICU decision support</em>
</p>
