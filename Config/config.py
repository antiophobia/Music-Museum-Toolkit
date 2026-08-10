"""
Music Museum Toolkit
Secure configuration loader

Credentials are read lazily from a local .env file in the project root.
Importing this module is safe when no credentials exist; Spotify API entrypoints
explicitly require them immediately before connecting.
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


class SpotifyConfigurationError(RuntimeError):
    """Raised only when a Spotify API action is requested without setup."""


def get_spotify_configuration():
    """Reload local configuration so setup can be completed after app startup."""
    _load_env_file(ENV_FILE)
    return {
        "client_id": os.getenv("SPOTIFY_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("SPOTIFY_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv(
            "SPOTIFY_REDIRECT_URI",
            "http://127.0.0.1:8888/callback",
        ).strip(),
    }


def _missing_names(configuration):
    names = {
        "SPOTIFY_CLIENT_ID": configuration["client_id"],
        "SPOTIFY_CLIENT_SECRET": configuration["client_secret"],
        "SPOTIFY_REDIRECT_URI": configuration["redirect_uri"],
    }
    return [name for name, value in names.items() if not value]


def missing_spotify_configuration():
    return _missing_names(get_spotify_configuration())


def require_spotify_configuration():
    configuration = get_spotify_configuration()
    missing = _missing_names(configuration)
    if missing:
        raise SpotifyConfigurationError(
            "Spotify API setup is required before Preserve or Restore can connect."
        )
    return configuration


# Backward-compatible, non-validating snapshots for callers that only inspect
# configuration. Connection code uses require_spotify_configuration() instead.
_configuration = get_spotify_configuration()
CLIENT_ID = _configuration["client_id"]
CLIENT_SECRET = _configuration["client_secret"]
REDIRECT_URI = _configuration["redirect_uri"]
