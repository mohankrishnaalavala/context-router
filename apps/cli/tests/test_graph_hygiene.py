"""CLI tests for 'context-router graph' hygiene fixes (v4.5).

Fix A: symbols whose file path falls under a config ignore pattern (or
outside the project root) must be dropped from the graph with a loud
stderr WARN — defense-in-depth for stale indexes built before v4.5.

Fix B: ``--json -o <path>`` writes the JSON payload to <path> instead of
silently ignoring -o; plain ``--json`` keeps printing to stdout so
existing pipelines don't break.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def _init_project(path: Path) -> None:
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(path)],
        check=True, capture_output=True,
    )


def _seed_symbols(root: Path, specs: list[tuple[str, Path]]) -> dict[str, int]:
    """Seed (name, file) function symbols into the project DB.

    Returns symbol ids keyed by name. Adds a 'calls' edge from the first
    seeded symbol to the second when at least two are given.
    """
    from contracts.interfaces import Symbol
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import EdgeRepository, SymbolRepository

    db_path = root / ".context-router" / "context-router.db"
    ids: dict[str, int] = {}
    with Database(db_path) as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        for name, file in specs:
            sym = Symbol(
                name=name,
                kind="function",
                file=file,
                line_start=1,
                line_end=5,
                language="python",
            )
            ids[name] = sym_repo.add(sym, "default")
        if len(specs) >= 2:
            first, second = specs[0][0], specs[1][0]
            edge_repo.add_raw("default", ids[first], ids[second], "calls")
    return ids


class TestGraphIgnoredPathHygiene:
    def test_graph_drops_ignored_paths_with_warning(self, tmp_path):
        """Stale-index symbols under ignored dirs must be dropped, loudly."""
        _init_project(tmp_path)
        _seed_symbols(
            tmp_path,
            [
                ("app_main", tmp_path / "app" / "main.py"),
                ("app_util", tmp_path / "app" / "util.py"),
                ("venv_a", tmp_path / ".venv-x" / "lib" / "a.py"),
                ("venv_b", tmp_path / ".venv-x" / "lib" / "b.py"),
                ("venv_c", tmp_path / ".venv-x" / "lib" / "c.py"),
            ],
        )

        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--json", "--no-open"]
        )
        assert result.exit_code == 0, result.output

        stdout_text = getattr(result, "stdout", result.output)
        json_payload = stdout_text[stdout_text.index("{"):]
        data = json.loads(json_payload)

        files = [n["file"] for n in data["nodes"]]
        assert files, "expected the non-ignored app/ symbols to survive"
        for f in files:
            assert ".venv-x" not in f, (
                f"ignored-path symbol leaked into graph: {f!r}"
            )

        combined = stdout_text + getattr(result, "stderr", "")
        assert "dropped" in combined, (
            f"dropping ignored-path symbols must WARN; streams={combined!r}"
        )
        assert "ignored paths" in combined, (
            f"WARN must name the reason (ignored paths); streams={combined!r}"
        )


class TestGraphJsonOutputFlag:
    def test_graph_json_with_output_writes_file(self, tmp_path):
        """--json -o <path> must write JSON to <path>, not ignore -o."""
        _init_project(tmp_path)
        out = tmp_path / "g.json"
        result = runner.invoke(
            app,
            [
                "graph",
                "--project-root", str(tmp_path),
                "--json",
                "--no-open",
                "-o", str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert out.exists(), "--json silently ignored -o; file not written"
        data = json.loads(out.read_text())
        assert "nodes" in data

    def test_graph_json_stdout_unchanged_without_o(self, tmp_path):
        """Regression guard: plain --json still prints JSON to stdout."""
        _init_project(tmp_path)
        result = runner.invoke(
            app, ["graph", "--project-root", str(tmp_path), "--json", "--no-open"]
        )
        assert result.exit_code == 0, result.output
        stdout_text = getattr(result, "stdout", result.output)
        data = json.loads(stdout_text)
        assert "nodes" in data
