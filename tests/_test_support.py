"""Test-only workspaces that avoid Python tempfile ACL issues on Windows."""

import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


@contextmanager
def synthetic_workspace():
    base = Path(__file__).resolve().parent / "_runtime_workspaces"
    root = base / ("case-" + uuid4().hex)
    root.mkdir(parents=True)
    try:
        yield str(root)
    finally:
        if root.exists():
            shutil.rmtree(root)
        if base.exists() and not any(base.iterdir()):
            base.rmdir()
