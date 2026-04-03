"""
start.py — One-command server launcher for HC01 backend.

Usage:
    python start.py              # starts on port 8080 (default)
    python start.py --port 9000  # custom port
"""
import os
import sys
import subprocess

# Fix Windows console encoding (prevents emoji UnicodeEncodeError)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Fix sentence-transformers symlink warning on Windows
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HUGGINGFACE_HUB_VERBOSITY", "warning")

# Default to port 8080 — avoids WinError 10013 that blocks port 8000
port = "8080"
if "--port" in sys.argv:
    idx = sys.argv.index("--port")
    if idx + 1 < len(sys.argv):
        port = sys.argv[idx + 1]

print(f"[HC01] Starting server on http://localhost:{port}")
print(f"[HC01] API docs: http://localhost:{port}/docs")
print(f"[HC01] Press Ctrl+C to stop\n")

cmd = [
    sys.executable, "-m", "uvicorn",
    "api.main:app",
    "--reload",
    "--port", port,
    "--host", "0.0.0.0",   # accessible from local network (useful for NFC demo)
]

try:
    subprocess.run(cmd)
except KeyboardInterrupt:
    print("\n[HC01] Server stopped.")
