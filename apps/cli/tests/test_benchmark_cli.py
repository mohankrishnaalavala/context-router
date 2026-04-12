"""CLI tests for 'context-router benchmark' commands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def _init_repo(path: Path) -> None:
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(path)],
        check=True, capture_output=True,
    )


def _cr(*args, **kwargs):
    return runner.invoke(app, list(args), catch_exceptions=False, **kwargs)


# ---------------------------------------------------------------------------
# benchmark run
# ---------------------------------------------------------------------------

class TestBenchmarkRun:
    def test_no_db_exits_1(self, tmp_path):
        result = _cr("benchmark", "run", "--project-root", str(tmp_path))
        assert result.exit_code == 1

    def test_run_creates_json_report(self, tmp_path):
        _init_repo(tmp_path)
        result = _cr(
            "benchmark", "run",
            "--project-root", str(tmp_path),
            "--no-naive", "--no-keyword",
        )
        assert result.exit_code == 0
        reports = list((tmp_path / ".context-router").glob("benchmark-*.json"))
        assert len(reports) == 1

    def test_run_creates_markdown_report(self, tmp_path):
        _init_repo(tmp_path)
        _cr(
            "benchmark", "run",
            "--project-root", str(tmp_path),
            "--no-naive", "--no-keyword",
        )
        reports = list((tmp_path / ".context-router").glob("benchmark-*.md"))
        assert len(reports) == 1

    def test_json_output_is_valid(self, tmp_path):
        _init_repo(tmp_path)
        result = _cr(
            "benchmark", "run",
            "--project-root", str(tmp_path),
            "--no-naive", "--no-keyword",
            "--json",
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "run_id" in data
        assert "tasks" in data
        assert len(data["tasks"]) == 20

    def test_custom_output_path(self, tmp_path):
        _init_repo(tmp_path)
        out = tmp_path / "my_report.json"
        _cr(
            "benchmark", "run",
            "--project-root", str(tmp_path),
            "--output", str(out),
            "--no-naive", "--no-keyword",
        )
        assert out.exists()


# ---------------------------------------------------------------------------
# benchmark report
# ---------------------------------------------------------------------------

class TestBenchmarkReport:
    def test_no_report_exits_1(self, tmp_path):
        _init_repo(tmp_path)
        result = _cr("benchmark", "report", "--project-root", str(tmp_path))
        assert result.exit_code == 1

    def test_reads_json_produces_markdown(self, tmp_path):
        _init_repo(tmp_path)
        # First generate a report
        _cr(
            "benchmark", "run",
            "--project-root", str(tmp_path),
            "--no-naive", "--no-keyword",
        )
        # Then read it back
        result = _cr("benchmark", "report", "--project-root", str(tmp_path))
        assert result.exit_code == 0
        assert "context-router Benchmark Results" in result.output

    def test_explicit_input_file(self, tmp_path):
        _init_repo(tmp_path)
        out = tmp_path / "report.json"
        _cr(
            "benchmark", "run",
            "--project-root", str(tmp_path),
            "--output", str(out),
            "--no-naive", "--no-keyword",
        )
        result = _cr("benchmark", "report", "--input", str(out))
        assert result.exit_code == 0

    def test_json_flag_outputs_json(self, tmp_path):
        _init_repo(tmp_path)
        out = tmp_path / "report.json"
        _cr(
            "benchmark", "run",
            "--project-root", str(tmp_path),
            "--output", str(out),
            "--no-naive", "--no-keyword",
        )
        result = _cr("benchmark", "report", "--input", str(out), "--json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "tasks" in data
