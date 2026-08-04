"""Repository paths shared by the local runtime modules."""
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
PROMPT_DIR = PROJECT_ROOT / "prompts"
STATE_DIR = DATA_DIR / "state"
PLAYWRIGHT_TMP_DIR = PROJECT_ROOT / ".playwright-tmp"
BROWSER_DIAGNOSTICS_DIR = DATA_DIR / "browser-diagnostics"

