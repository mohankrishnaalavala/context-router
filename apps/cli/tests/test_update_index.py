"""Tests for `context-router update-index --file` — single-file incremental update.

Contract (v4.6 spec B2 + hooks DoD): this command is invoked from editor
hooks on every file edit, so it must NEVER break the editing session:

  * file outside project root      → exit 0 + named stderr notice
  * non-indexable extension (.md)  → exit 0 + named stderr notice
  * missing index DB               → exit 0 + stderr WARN suggesting
                                     'context-router index'
  * no project root discoverable   → exit 0 + stderr WARN

Happy path: the file's symbols land in the index without a full re-index.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def _make_indexed_project(tmp_path: Path) -> Path:
    """Create a minimal project, init it, and build a full index."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "existing.py").write_text("def existing_fn():\n    return 1\n")
    result = runner.invoke(app, ["init", "--project-root", str(root)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["index", "--project-root", str(root)])
    assert result.exit_code == 0, result.output
    return root


def _symbol_count_for(root: Path, file_path: Path) -> int:
    db = root / ".context-router" / "context-router.db"
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE file_path = ?", (str(file_path),)
        ).fetchone()
        return int(row[0])
    finally:
        conn.close()


# ── happy path ────────────────────────────────────────────────────────────────


class TestUpdateIndexHappyPath:
    def test_new_file_is_indexed(self, tmp_path: Path) -> None:
        root = _make_indexed_project(tmp_path)
        new_file = root / "fresh.py"
        new_file.write_text("def fresh_symbol():\n    return 42\n")
        assert _symbol_count_for(root, new_file) == 0

        result = runner.invoke(
            app,
            ["update-index", "--file", str(new_file), "--project-root", str(root)],
        )
        assert result.exit_code == 0, result.output
        assert _symbol_count_for(root, new_file) >= 1

    def test_deleted_file_rows_are_removed(self, tmp_path: Path) -> None:
        root = _make_indexed_project(tmp_path)
        target = root / "existing.py"
        assert _symbol_count_for(root, target) >= 1
        target.unlink()

        result = runner.invoke(
            app,
            ["update-index", "--file", str(target), "--project-root", str(root)],
        )
        assert result.exit_code == 0, result.output
        assert _symbol_count_for(root, target) == 0

    def test_help_exits_0(self) -> None:
        result = runner.invoke(app, ["update-index", "--help"])
        assert result.exit_code == 0
        assert "--file" in result.output


# ── negative cases (DoD: hook must never break the editing session) ─────────


class TestUpdateIndexNegativeCases:
    def test_file_outside_project_root_exits_0_with_notice(
        self, tmp_path: Path
    ) -> None:
        root = _make_indexed_project(tmp_path)
        outside = tmp_path / "elsewhere.py"
        outside.write_text("def nope():\n    pass\n")

        result = runner.invoke(
            app,
            ["update-index", "--file", str(outside), "--project-root", str(root)],
        )
        assert result.exit_code == 0, result.output
        assert "outside project root" in result.stderr

    def test_non_indexable_extension_exits_0_with_notice(
        self, tmp_path: Path
    ) -> None:
        root = _make_indexed_project(tmp_path)
        notes = root / "NOTES.md"
        notes.write_text("# notes\n")

        result = runner.invoke(
            app,
            ["update-index", "--file", str(notes), "--project-root", str(root)],
        )
        assert result.exit_code == 0, result.output
        assert "no analyzer registered" in result.stderr

    def test_missing_index_db_exits_0_with_warn(self, tmp_path: Path) -> None:
        root = tmp_path / "proj"
        (root / ".context-router").mkdir(parents=True)
        target = root / "thing.py"
        target.write_text("def thing():\n    pass\n")

        result = runner.invoke(
            app,
            ["update-index", "--file", str(target), "--project-root", str(root)],
        )
        assert result.exit_code == 0, result.output
        assert "WARN" in result.stderr
        assert "context-router index" in result.stderr

    def test_no_project_root_found_exits_0_with_warn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        target = bare / "thing.py"
        target.write_text("def thing():\n    pass\n")
        monkeypatch.chdir(bare)

        result = runner.invoke(app, ["update-index", "--file", str(target)])
        assert result.exit_code == 0, result.output
        assert "WARN" in result.stderr
