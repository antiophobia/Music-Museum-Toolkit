"""Portable first-run initialization and privacy-conscious error logging."""

from __future__ import annotations

import os
import traceback
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_VERSION = "v0.4.0 + Museum development build"
RUNTIME_DIRECTORIES = (
    Path("Input"),
    Path("Input") / "Spotify Data",
    Path("Output"),
    Path("Logs"),
)
SENSITIVE_ENV_MARKERS = (
    "CLIENT_SECRET", "TOKEN",
)


def initialize_runtime_directories(project_root=None):
    """Create missing Toolkit-owned directories without touching their contents."""
    root = Path(project_root or PROJECT_ROOT).resolve()
    created_or_existing = []
    for relative in RUNTIME_DIRECTORIES:
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        created_or_existing.append(path)
    return created_or_existing


def _redact(text, project_root):
    sanitized = str(text)
    root = str(Path(project_root).resolve())
    sanitized = sanitized.replace(root, "<PROJECT_ROOT>")
    home = str(Path.home())
    if home and home != root:
        sanitized = sanitized.replace(home, "<USER_HOME>")
    for key, value in os.environ.items():
        if any(marker in key.upper() for marker in SENSITIVE_ENV_MARKERS):
            secret = str(value).strip()
            if len(secret) >= 4:
                sanitized = sanitized.replace(secret, "<REDACTED>")
    return sanitized


def write_error_log(context, error, project_root=None):
    """Write a sanitized traceback without exporting user data or credentials."""
    root = Path(project_root or PROJECT_ROOT).resolve()
    logs = root / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    filename = timestamp.strftime("error-%Y%m%dT%H%M%S%fZ.log")
    # Stack frames and exception type are enough to locate a programming fault.
    # The exception message is deliberately excluded because a third-party
    # parser or API could include private export data or credentials in it.
    trace = "".join(traceback.format_list(
        traceback.extract_tb(error.__traceback__)
    ))
    contents = (
        "Music Museum Toolkit error report\n"
        f"Time (UTC): {timestamp.isoformat()}\n"
        f"Context: {context}\n"
        f"Exception type: {type(error).__name__}\n\n"
        + "Traceback (stack only):\n"
        + _redact(trace, root)
    )
    path = logs / filename
    path.write_text(contents, encoding="utf-8")
    return path


def display_path(path, project_root=None):
    """Return a short relocatable path for ordinary user-facing messages."""
    root = Path(project_root or PROJECT_ROOT).resolve()
    try:
        relative = Path(path).resolve().relative_to(root)
    except ValueError:
        return Path(path).name
    return str(relative).replace("/", "\\")
