"""
config.py  Centralised environment variable loading for HC01 backend.

All modules import from here instead of calling os.getenv directly.
This makes it easy to validate config and change defaults in one place.
"""
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
STORAGE_BUCKET: str = os.getenv("STORAGE_BUCKET", "hc01-patient-files")
STORAGE_UPLOAD_ENABLED: bool = os.getenv(
    "STORAGE_UPLOAD_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}

OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "phi3:mini")
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_NUM_GPU: int = int(os.getenv("OLLAMA_NUM_GPU", "99"))
OLLAMA_NUM_PREDICT: int = int(os.getenv("OLLAMA_NUM_PREDICT", "256"))

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
CHIEF_PROVIDER: str = os.getenv("CHIEF_PROVIDER", "auto").strip().lower()
CHIEF_ALLOW_GEMINI_FALLBACK: bool = os.getenv(
    "CHIEF_ALLOW_GEMINI_FALLBACK", "false"
).strip().lower() in {"1", "true", "yes", "on"}

CHROMA_PERSIST_PATH: str = os.getenv("CHROMA_PERSIST_PATH", "./chroma_db")
CHROMA_COLLECTION_NAME: str = os.getenv("CHROMA_COLLECTION_NAME", "clinical_guidelines")

FAMILY_REGIONAL_LANGUAGE_NAME: str = os.getenv("FAMILY_REGIONAL_LANGUAGE_NAME", "Hindi")
FAMILY_REGIONAL_LANGUAGE_CODE: str = os.getenv("FAMILY_REGIONAL_LANGUAGE_CODE", "hi")


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
        print("\n  HC01 Config Warning  missing environment variables:")
        for var in missing:
            print(f"    {var}")
        print("    Copy .env.example to .env and fill in the values.\n")
        return False

    print(" HC01 Config OK  all required environment variables are set.")
    return True
