"""v4.6 A3 — `context-router index` summary consistency
(DoD: v4.6-edge-count-consistency).

The edge count printed by the index command must equal the rows stored in
the database, on the first run and on an immediate re-run.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

SOURCE = '''"""Small module with internal calls."""


def helper(n: int) -> int:
    """Return n."""
    return n


def caller() -> int:
    """Call helper repeatedly."""
    return helper(1) + helper(2) + helper(1)


class Base:
    """Base class."""


class Child(Base):
    """Subclass."""
'''


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(SOURCE)
    result = runner.invoke(app, ["init", "--project-root", str(tmp_path)])
    assert result.exit_code == 0
    return tmp_path


def _stored_edge_count(project: Path) -> int:
    conn = sqlite3.connect(project / ".context-router" / "context-router.db")
    try:
        return conn.execute("SELECT count(*) FROM edges").fetchone()[0]
    finally:
        conn.close()


def _run_index_json(project: Path) -> dict:
    result = runner.invoke(
        app, ["index", "--project-root", str(project), "--json"]
    )
    assert result.exit_code == 0
    return json.loads(result.output.strip().splitlines()[-1])


def test_edge_count_reported_equals_stored(project: Path) -> None:
    payload = _run_index_json(project)
    assert payload["edges_written"] == _stored_edge_count(project)
    assert payload["edges_written"] > 0


def test_edge_count_identical_on_immediate_rerun(project: Path) -> None:
    first = _run_index_json(project)
    second = _run_index_json(project)
    assert second["edges_written"] == _stored_edge_count(project)
    assert first["edges_written"] == second["edges_written"]
