"""CLI tests for 'context-router graph' command."""

from __future__ import annotations
import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner
from cli.main import app

runner = CliRunner()


def _init_and_index(path: Path) -> None:
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(path)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["uv", "run", "context-router", "index", "--project-root", str(path)],
        check=True, capture_output=True,
    )


class TestGraphCommand:
    def test_no_db_exits_1(self, tmp_path):
        result = runner.invoke(app, ["graph", "--project-root", str(tmp_path)])
        assert result.exit_code == 1

    def test_generates_html_file(self, tmp_path):
        _init_and_index(tmp_path)
        out = tmp_path / "out.html"
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--output", str(out)]
        )
        assert result.exit_code == 0
        assert out.exists()
        content = out.read_text()
        assert "context-router graph" in content
        assert "d3js.org" in content

    def test_json_output(self, tmp_path):
        _init_and_index(tmp_path)
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "nodes" in data
        assert "links" in data
