"""Production entrypoint for the GPT Memory Service.

Run with ``python main.py`` to start uvicorn without auto-reload. For
local development, prefer ``uvicorn gpt_memory_service.app:app --reload``
from the repository root (with ``PYTHONPATH=src``).
"""

from pathlib import Path
import sys

import uvicorn

# Ensure the src/ directory is on the import path when running without installing the package
ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from gpt_memory_service.app import app  # noqa: E402

if __name__ == "__main__":
    print(f"Starting GPT Memory Service v2.0.0")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
