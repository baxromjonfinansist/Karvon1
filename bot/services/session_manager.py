from __future__ import annotations

from pathlib import Path

SESSION_DIR = Path("data")
SESSION_PATH = SESSION_DIR / "telethon_session"


def get_session_path() -> str:
    """Return absolute session file path, creating the data/ dir if needed."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return str(SESSION_PATH)
