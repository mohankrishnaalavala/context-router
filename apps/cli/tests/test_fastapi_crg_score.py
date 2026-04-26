from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_score_module():
    score_path = Path(__file__).resolve().parents[3] / "eval" / "fastapi-crg" / "score.py"
    spec = importlib.util.spec_from_file_location("fastapi_crg_score", score_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    old_path = sys.path[:]
    sys.path.insert(0, str(score_path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
    return module


score = _load_score_module()


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_score_writes_diagnostics_json(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(
        """
tasks:
  - id: task1
    description: "source miss"
    ground_truth_files:
      - app/source.py
""",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "cr_task1.json",
        {
            "selected_items": [
                {
                    "path_or_ref": "/repo/tests/test_source.py",
                    "source_type": "failing_test",
                    "confidence": 0.85,
                    "est_tokens": 50,
                    "title": "test_source",
                }
            ]
        },
    )
    _write_json(
        tmp_path / "crg_task1.json",
        {"changed_functions": [{"file_path": "app/source.py"}]},
    )

    rc = score.main(
        [
            "--tasks",
            str(tasks),
            "--output-dir",
            str(tmp_path),
            "--fastapi-root",
            "/repo",
            "--diagnostics-json",
            "diagnostics.json",
        ]
    )

    assert rc == 0
    diagnostics = json.loads((tmp_path / "diagnostics.json").read_text())
    assert diagnostics["aggregate"]["context_router"]["avg_f1"] == 0.0
    assert diagnostics["aggregate"]["code_review_graph"]["avg_f1"] == 1.0
    assert diagnostics["tasks"][0]["context_router"]["missing_ground_truth"] == ["app/source.py"]
    assert diagnostics["tasks"][0]["context_router"]["source_type_counts"] == {"failing_test": 1}


def test_gate_fails_when_context_router_lags_crg(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.yaml"
    tasks.write_text(
        """
tasks:
  - id: task1
    description: "source miss"
    ground_truth_files:
      - app/source.py
""",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "cr_task1.json",
        {"selected_items": [{"path_or_ref": "/repo/tests/test_source.py", "est_tokens": 50}]},
    )
    _write_json(
        tmp_path / "crg_task1.json",
        {"changed_functions": [{"file_path": "app/source.py"}]},
    )

    rc = score.main(
        [
            "--tasks",
            str(tasks),
            "--output-dir",
            str(tmp_path),
            "--fastapi-root",
            "/repo",
            "--gate",
            "--min-cr-f1",
            "0.80",
            "--min-crg-f1-ratio",
            "1.00",
        ]
    )

    assert rc == 3
