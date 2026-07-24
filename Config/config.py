"""
Music Museum Toolkit
Secure configuration loader

Credentials are read from a local .env file in the project root.
The .env file must never be committed to Git.
"""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without requiring an external package."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        # Existing system environment variables take priority.
        os.environ.setdefault(key, value)


_load_env_file(ENV_FILE)

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv(
    "SPOTIFY_REDIRECT_URI",
    "http://127.0.0.1:8888/callback",
).strip()


_missing = [
    name
    for name, value in {
        "SPOTIFY_CLIENT_ID": CLIENT_ID,
        "SPOTIFY_CLIENT_SECRET": CLIENT_SECRET,
        "SPOTIFY_REDIRECT_URI": REDIRECT_URI,
    }.items()
    if not value
]

if _missing:
    missing_text = ", ".join(_missing)
    raise RuntimeError(
        "Missing Spotify configuration: "
        f"{missing_text}. Copy .env.example to .env and fill in your values."
    )