"""CLI tests for ``context-router audit --untested-hotspots``.

Covers:
  * Ranking a seeded fixture DB — hot + untested symbols surface, hot +
    tested symbols are suppressed, and ordering is by inbound degree
    descending.
  * Silent-failure guard: a DB with zero ``tested_by`` edges emits a
    stderr warning and exits 0 with empty stdout (not an error).
  * ``--limit`` caps the number of returned rows.
  * ``--json`` output is machine-parseable.
  * Unknown ``--project-root`` (no DB) exits 1.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cli.main import app
from typer.testing import CliRunner

# Click/Typer >=0.24 already separates stdout and stderr by default, so
# no ``mix_stderr`` argument is needed.  Tests below assert on
# ``result.stdout`` and ``result.stderr`` independently.
runner = CliRunner()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _init(path: Path) -> None:
    """Create ``.context-router/context-router.db`` with the full schema."""
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(path)],
        check=True,
        capture_output=True,
    )


def _seed(
    path: Path,
    *,
    with_tested_by: bool = True,
) -> dict[str, int]:
    """Seed a fixture with known hot / tested / untested symbols.

    Layout:
      hot_untested  ← 3 inbound calls, no tested_by
      hot_tested    ← 3 inbound calls, 1 tested_by
      less_hot      ← 1 inbound call,  no tested_by
      caller_{1,2,3}   — plain callers
      test_hot_tested — the test function pointed at by tested_by
    """
    _init(path)

    from contracts.interfaces import Symbol
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import EdgeRepository, SymbolRepository

    db_path = path / ".context-router" / "context-router.db"
    ids: dict[str, int] = {}
    with Database(db_path) as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)

        def _add(name: str, file: str) -> int:
            sym = Symbol(
                name=name,
                kind="function",
                file=Path(file),
                line_start=10,
                line_end=20,
                language="python",
            )
            return sym_repo.add(sym, "default")

        ids["hot_untested"] = _add("hot_untested", "/src/hot_untested.py")
        ids["hot_tested"] = _add("hot_tested", "/src/hot_tested.py")
        ids["less_hot"] = _add("less_hot", "/src/less_hot.py")
        for i in (1, 2, 3):
            ids[f"caller_{i}"] = _add(f"caller_{i}", f"/src/caller_{i}.py")
        ids["test_hot_tested"] = _add("test_hot_tested", "/tests/test_hot_tested.py")

        for i in (1, 2, 3):
            edge_repo.add_raw("default", ids[f"caller_{i}"], ids["hot_untested"], "calls")
            edge_repo.add_raw("default", ids[f"caller_{i}"], ids["hot_tested"], "calls")
        edge_repo.add_raw("default", ids["caller_1"], ids["less_hot"], "calls")

        if with_tested_by:
            edge_repo.add_raw(
                "default", ids["hot_tested"], ids["test_hot_tested"], "tested_by"
            )
    return ids


# ---------------------------------------------------------------------------
# positive path
# ---------------------------------------------------------------------------


class TestAuditUntestedHotspots:
    def test_ranks_untested_above_tested_and_sorts_desc(self, tmp_path):
        _seed(tmp_path, with_tested_by=True)

        result = runner.invoke(
            app,
            [
                "audit",
                "--untested-hotspots",
                "--project-root",
                str(tmp_path),
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        names = [row["name"] for row in payload["items"]]

        # hot_tested is the target of a tested_by edge → must be excluded.
        assert "hot_tested" not in names
        # hot_untested is hot and untested → must appear.
        assert "hot_untested" in names
        # Rows must be sorted by inbound degree descending.
        inbound_values = [row["inbound"] for row in payload["items"]]
        assert inbound_values == sorted(inbound_values, reverse=True)
        # Every row must carry the explicit ``reason`` field.
        assert all(row["reason"] == "untested" for row in payload["items"])

    def test_human_output_contains_untested_marker(self, tmp_path):
        _seed(tmp_path, with_tested_by=True)
        result = runner.invoke(
            app,
            [
                "audit",
                "--untested-hotspots",
                "--project-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        # Smoke registry substring check — "untested" must be present
        # verbatim in stdout so the smoke script's head -5 | grep works.
        assert "untested" in result.stdout
        assert "hot_untested" in result.stdout

    def test_limit_caps_rows(self, tmp_path):
        _seed(tmp_path, with_tested_by=True)
        result = runner.invoke(
            app,
            [
                "audit",
                "--untested-hotspots",
                "--project-root",
                str(tmp_path),
                "--limit",
                "1",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert len(payload["items"]) <= 1


# ---------------------------------------------------------------------------
# negative / silent-failure guards
# ---------------------------------------------------------------------------


class TestAuditNoCoverage:
    def test_zero_tested_by_edges_warns_and_exits_0(self, tmp_path):
        """Per CLAUDE.md silent-failure rule: when no tested_by edges exist
        the command MUST surface a stderr warning and exit 0 with empty
        stdout — not silently emit an empty list."""
        _seed(tmp_path, with_tested_by=False)

        result = runner.invoke(
            app,
            [
                "audit",
                "--untested-hotspots",
                "--project-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        assert result.stdout.strip() == ""
        # stderr must name the reason.
        assert "tested_by" in result.stderr.lower() or "TESTED_BY" in result.stderr

    def test_zero_tested_by_edges_json_emits_empty_items(self, tmp_path):
        _seed(tmp_path, with_tested_by=False)
        result = runner.invoke(
            app,
            [
                "audit",
                "--untested-hotspots",
                "--project-root",
                str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload == {"items": []}
        assert "TESTED_BY" in result.stderr or "tested_by" in result.stderr.lower()


class TestAuditErrors:
    def test_missing_project_root_db_exits_1(self, tmp_path):
        """An unknown project root (no DB) should exit 1 with a clear message."""
        result = runner.invoke(
            app,
            [
                "audit",
                "--untested-hotspots",
                "--project-root",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 1
        combined = (result.stdout + result.stderr).lower()
        assert "no index" in combined or "not found" in combined

    def test_no_flag_prints_usage_hint(self, tmp_path):
        """Running `audit` with no flag should not crash — print hint."""
        _seed(tmp_path, with_tested_by=True)
        result = runner.invoke(
            app,
            ["audit", "--project-root", str(tmp_path)],
        )
        assert result.exit_code == 0
        # Usage hint goes to stderr so CI scripts can detect the missing
        # flag without parsing stdout.
        assert "--untested-hotspots" in (result.stdout + result.stderr)
