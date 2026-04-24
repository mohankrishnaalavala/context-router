from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_workspace"


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture lands in Task 7")
def test_eval_runs_and_emits_json():
    out = subprocess.run(
        [
            sys.executable, "-m", "cli.main", "eval",
            "--queries", str(FIXTURE / "queries.jsonl"),
            "--project-root", str(FIXTURE / "backend"),
            "--k", "20",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, f"stderr: {out.stderr}"
    payload = json.loads(out.stdout)
    assert "recall_at_k" in payload
    assert payload["k"] == 20
    assert 0.0 <= payload["recall_at_k"] <= 1.0
    assert payload["n_queries"] >= 1
