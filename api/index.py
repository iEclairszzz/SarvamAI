"""Vercel Python entrypoint.

Vercel's Python runtime looks for a module-level ASGI app named ``app`` in the
entrypoint file, so we simply re-export the FastAPI application here.
"""

import sys
from pathlib import Path

# Ensure the repository root is importable when this file is executed by the
# Vercel runtime (the working directory can differ from the project root).
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import app  # noqa: E402,F401
