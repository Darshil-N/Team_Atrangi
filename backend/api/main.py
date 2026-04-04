"""
api/main.py  FastAPI application entry point for HC01.

Run from the backend/ directory:
    uvicorn api.main:app --reload --port 8000

API docs available at: http://localhost:8000/docs
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once at startup, then yields while the server is alive."""
    print("\n[HC01] Diagnostic Risk Assistant -- starting up...")
    config.validate_config()
    print("[HC01] FastAPI server ready.\n")
    yield
    print("[HC01] Server shutting down.")



app = FastAPI(
    title="HC01 Diagnostic Risk Assistant",
    description=(
        "Multi-agent AI system for ICU complication detection. "
        "Combines local LLMs (Ollama/phi3:mini), vector RAG (ChromaDB), "
        "and cloud synthesis (Gemini) to produce structured diagnostic reports."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/", tags=["root"])
async def root():
    return {
        "message": "HC01 API is running.",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", tags=["root"])
async def health_check():
    return {
        "status": "ok",
        "service": "HC01 Diagnostic Risk Assistant",
        "version": "0.1.0",
        "ollama_model": config.OLLAMA_MODEL,
        "gemini_model": config.GEMINI_MODEL,
    }



from api.routes import patients, upload, reports  # noqa: E402  (import after app creation)

app.include_router(patients.router, prefix="/patients", tags=["patients"])
app.include_router(upload.router,   prefix="/upload",   tags=["upload"])
app.include_router(reports.router,  prefix="/reports",  tags=["reports"])
