from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_TINY_WORKSPACE_BACKEND = Path(__file__).parent / "fixtures" / "tiny_workspace" / "backend"
_CR_DIR = _TINY_WORKSPACE_BACKEND / ".context-router"


def _ensure_fixture_indexed() -> None:
    """Init + index the tiny_workspace fixture if not already done."""
    if _CR_DIR.exists():
        return
    for cmd in (["init"], ["index"]):
        subprocess.run(
            [sys.executable, "-m", "cli.main", *cmd,
             "--project-root", str(_TINY_WORKSPACE_BACKEND)],
            capture_output=True,
            check=False,
        )


if _TINY_WORKSPACE_BACKEND.exists():
    _ensure_fixture_indexed()
