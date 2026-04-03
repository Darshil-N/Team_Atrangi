"""
config.py — Centralised environment variable loading for HC01 backend.

All modules import from here instead of calling os.getenv directly.
This makes it easy to validate config and change defaults in one place.
"""
import os
from dotenv import load_dotenv

# load .env file (safe to call even if .env doesn't exist)
load_dotenv()

# ── Supabase ──────────────────────────────────────────────
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

# ── Ollama (local LLM) ────────────────────────────────────
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "phi3:mini")
# num_ctx caps the KV-cache size → keeps VRAM under 6 GB ceiling on RTX 3050
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
# num_gpu=99 forces every model layer onto the GPU — no silent RAM offload
OLLAMA_NUM_GPU: int = int(os.getenv("OLLAMA_NUM_GPU", "99"))

# ── Google Gemini (cloud synthesis agent) ─────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# ── ChromaDB (local vector store) ────────────────────────
CHROMA_PERSIST_PATH: str = os.getenv("CHROMA_PERSIST_PATH", "./chroma_db")
CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION_NAME", "clinical_guidelines")


def validate_config() -> bool:
    """
    Check that all required environment variables are set.
    Prints a clear warning for each missing variable.
    Returns True if config is complete, False otherwise.

    Called once at FastAPI startup so problems surface immediately.
    """
    required = {
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_KEY,
        "GEMINI_API_KEY": GEMINI_API_KEY,
    }

    missing = [name for name, value in required.items() if not value]

    if missing:
        print("\n⚠️  HC01 Config Warning — missing environment variables:")
        for var in missing:
            print(f"   • {var}")
        print("   → Copy .env.example to .env and fill in the values.\n")
        return False

    print("✅ HC01 Config OK — all required environment variables are set.")
    return True
