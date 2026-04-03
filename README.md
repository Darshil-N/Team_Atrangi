<p align="center">
  <img src="../Logo.jpeg" alt="Saanjivani Logo" width="160"/>
</p>

<h1 align="center">Saanjivani — HC01 Diagnostic Risk Assistant</h1>

<p align="center">
  <strong>A multi-agent AI system for real-time ICU complication detection</strong><br/>
  Built for hackathon track HC01 · Team Atrangi
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.13-blue?logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-latest-009688?logo=fastapi&logoColor=white"/>
  <img src="https://img.shields.io/badge/Ollama-phi3%3Amini-black?logo=ollama"/>
  <img src="https://img.shields.io/badge/Gemini-1.5%20Flash-4285F4?logo=google&logoColor=white"/>
  <img src="https://img.shields.io/badge/Supabase-PostgreSQL-3ECF8E?logo=supabase&logoColor=white"/>
  <img src="https://img.shields.io/badge/ChromaDB-Vector%20Store-FF6B6B"/>
</p>

---

## What It Does

Saanjivani is an **agentic AI diagnostic assistant** for ICU physicians. It continuously monitors a patient's clinical notes and lab results, detects emerging complications (sepsis, organ failure), retrieves evidence-based guidelines, and generates structured diagnostic reports — all in real time.

**The core innovation**: the system refuses to update a diagnosis when lab values are statistically impossible (e.g., K⁺ = 14.0 mmol/L). Instead of hallucinating a conclusion from corrupted data, it flags the probable lab error and preserves the prior clinical assessment.

---

## Architecture

```
                        ┌──────────────────────────────┐
                        │        FastAPI Backend        │
                        │   POST /reports/analyse       │
                        └────────────┬─────────────────┘
                                     │ BackgroundTask
                   ┌─────────────────▼──────────────────┐
                   │          Orchestrator               │
                   │      agents/orchestrator.py         │
                   └──┬──────────────┬──────────────────┘
          asyncio.gather             │
       ┌────────┴──────┐             │ sequential
       ▼               ▼             ▼
 ┌───────────┐  ┌────────────┐  ┌──────────────────┐
 │note_parser│  │ lab_mapper │  │    rag_agent      │
 │           │  │            │  │                   │
 │ Ollama    │  │ Pandas +   │  │ ChromaDB          │
 │ phi3:mini │  │ Scipy +    │  │ all-MiniLM-L6-v2 │
 │           │  │ Ollama     │  │ (no LLM needed)  │
 └─────┬─────┘  └─────┬──────┘  └────────┬─────────┘
       └──────────────┴──────────────────┘
                       │ all outputs
                       ▼
            ┌──────────────────────┐
            │    chief_agent       │
            │  Gemini 1.5 Flash    │
            │  + Outlier Guard     │
            └──────────┬───────────┘
                       │
                       ▼
              ┌─────────────────┐
              │   Supabase DB   │
              │  reports table  │
              └─────────────────┘
```

---

## Agent Pipeline

| Agent | Model | Role |
|-------|-------|------|
| `note_parser` | Ollama `phi3:mini` | Extracts symptoms from unstructured clinical notes |
| `lab_mapper` | Pandas + `phi3:mini` | Computes trends, detects statistical outliers (3σ rule) |
| `rag_agent` | ChromaDB (no LLM) | Retrieves relevant clinical guidelines by semantic similarity |
| `chief_agent` | Gemini 1.5 Flash | Synthesises all inputs into a structured diagnostic report |

### The Outlier Refusal System (3-Layer Guard)

When a lab value is physiologically impossible:

```
Layer 1 → lab_mapper:   Pandas 3σ detection flags the value statistically
Layer 2 → chief prompt: Gemini explicitly instructed to set diagnosis_updated=false
Layer 3 → Python guard: _apply_outlier_guard() overrides any Gemini misjudgement
```

Even if Gemini hallucinates, Layer 3 catches it.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **API** | FastAPI + Uvicorn |
| **Local LLM** | Ollama `phi3:mini` (~2.3 GB VRAM) |
| **Cloud AI** | Google Gemini 1.5 Flash |
| **Vector DB** | ChromaDB + `all-MiniLM-L6-v2` embeddings |
| **Database** | Supabase (PostgreSQL) |
| **ML / Stats** | Pandas, NumPy, Scipy |
| **Document Parsing** | pdfplumber, PyPDF2 |
| **Orchestration** | LangChain + asyncio |

### VRAM Budget (6 GB RTX 3050)

| Component | VRAM |
|-----------|------|
| phi3:mini weights | ~2.3 GB |
| KV cache @ ctx=4096 | ~1.5 GB |
| ChromaDB embeddings | CPU only |
| **Total** | **~3.8 GB** (2.2 GB headroom) |

---

## Project Structure

```
Team_Atrangi/
├── backend/
│   ├── api/
│   │   ├── main.py               # FastAPI entry point
│   │   ├── models.py             # Pydantic schemas
│   │   └── routes/
│   │       ├── patients.py       # Patient CRUD
│   │       ├── upload.py         # File ingestion (WIP)
│   │       └── reports.py        # Analysis trigger + retrieval
│   ├── agents/
│   │   ├── note_parser.py        # Agent 1 — symptom extraction
│   │   ├── lab_mapper.py         # Agent 2 — lab trends + outlier detection
│   │   ├── rag_agent.py          # Agent 3 — guideline retrieval
│   │   ├── chief_agent.py        # Agent 4 — Gemini synthesis
│   │   └── orchestrator.py       # Pipeline coordinator
│   ├── database/
│   │   ├── supabase_client.py    # DB connection + CRUD
│   │   └── schema.sql            # PostgreSQL schema
│   ├── processing/
│   │   └── state_builder.py      # Unified patient state assembler
│   ├── vector_db/
│   │   ├── chroma_setup.py       # ChromaDB initialisation
│   │   └── load_guidelines.py    # Seed + PDF guideline ingestion
│   ├── config.py                 # Environment config + validation
│   ├── requirements.txt          # Python dependencies
│   ├── start.py                  # One-command server launcher
│   └── test_pipeline.py          # End-to-end test (3 scenarios)
└── schema.sql                    # Supabase SQL schema reference
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai) installed
- Supabase project (free tier works)
- Google Gemini API key

### 1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure environment

```bash
copy .env.example .env
# Fill in: SUPABASE_URL, SUPABASE_KEY, GEMINI_API_KEY
```

### 3. Set up the database

Run `backend/database/schema.sql` in the Supabase SQL Editor.

### 4. Pull the local model

```bash
ollama pull phi3:mini
```

### 5. Seed clinical guidelines

```bash
python -m vector_db.load_guidelines
```

### 6. Start the server

```bash
python start.py
```

**API docs → http://localhost:8080/docs**

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check + config status |
| `POST` | `/reports/analyse` | Trigger the full agent pipeline |
| `GET` | `/reports/{patient_id}/current` | Fetch latest diagnostic report |
| `GET` | `/docs` | Interactive Swagger UI |

### Trigger analysis

```bash
curl -X POST http://localhost:8080/reports/analyse \
  -H "Content-Type: application/json" \
  -d '{"patient_id": "your-patient-uuid"}'
```

---

## Running Tests

No server required — tests call the pipeline directly in Python:

```bash
cd backend

# Test Case A: Stable patient — no false positives
python test_pipeline.py

# Test Case B: Sepsis — HIGH risk flag + guideline citation
python test_pipeline.py --sepsis

# Test Case C: K+=14.0 impossible value — outlier refusal
python test_pipeline.py --outlier
```

### Expected output for Test Case C

```
ASSERTIONS
  PASS — diagnosis_updated is False
  PASS — outlier_alerts present
  PASS — Potassium flagged as: PROBABLE LAB ERROR
```

---

## Key Design Decisions

**Why `phi3:mini` over `llama3.1:8b`?**
Llama 3.1 leaves only ~1.3 GB VRAM when idle. Processing dense ICU notes fills the KV cache and spills to system RAM, causing mid-demo stalls. `phi3:mini` keeps the footprint at ~3.8 GB — safe under full load.

**Why two LLMs (phi3 + Gemini)?**
phi3:mini handles fast local extraction tasks offline. Gemini Flash handles final synthesis which requires long-context reasoning across all agent outputs — beyond phi3's capacity within the VRAM budget.

**Why is the RAG agent LLM-free?**
Vector similarity is deterministic and needs no LLM. Adding one would only increase latency and VRAM pressure — the chief agent already reasons over retrieved guidelines.

---

<p align="center">
  <em>Saanjivani — "That which restores life"</em><br/>
  Team Atrangi · HC01 Hackathon
</p>