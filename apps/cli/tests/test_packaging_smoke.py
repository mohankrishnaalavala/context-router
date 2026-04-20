"""Integration: scripts/smoke-packaging.sh end-to-end.

This test is slow (builds a wheel, creates a venv, pip-installs, runs
the CLI) so it is gated behind ``CR_PACKAGING_SMOKE=1``. Default CI
skips it; the release gate sets the env var and must see it PASS.

Outcome under test (registry id: ``packaging-fresh-install``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke-packaging.sh"


pytestmark = pytest.mark.skipif(
    os.environ.get("CR_PACKAGING_SMOKE") != "1",
    reason=(
        "slow (wheel build + clean venv + pip install). "
        "Set CR_PACKAGING_SMOKE=1 to enable."
    ),
)


class TestPackagingSmokeScript:
    def test_script_exists_and_is_executable(self) -> None:
        assert SMOKE_SCRIPT.exists(), f"missing: {SMOKE_SCRIPT}"
        assert os.access(SMOKE_SCRIPT, os.X_OK), "smoke-packaging.sh is not executable"

    def test_fresh_install_produces_symbols(self) -> None:
        """Invoke the script and assert it prints PASS packaging-fresh-install."""
        proc = subprocess.run(
            ["bash", str(SMOKE_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert proc.returncode == 0, (
            f"smoke-packaging.sh failed (rc={proc.returncode}):\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
        assert "PASS packaging-fresh-install" in proc.stdout, proc.stdout
