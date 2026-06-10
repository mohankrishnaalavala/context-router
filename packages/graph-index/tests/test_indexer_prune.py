"""Full Indexer.run() must prune symbols whose files no longer pass the scanner.

DBs indexed before the v4.5 ignore-pattern fix may contain symbols from
directories like `.venv-crg/` that the scanner now skips. A full run() must
heal such databases: delete the stale symbols and their edges, and report the
prune count to stderr (no-silent-failure policy).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.config import ContextRouterConfig
from core.plugin_loader import PluginLoader
from graph_index.indexer import Indexer
from storage_sqlite.database import Database

REPO = "test-repo"

VALID_SOURCE = '''"""A real module the scanner accepts."""


def greet(name: str) -> str:
    """Return a greeting."""
    return f"hello {name}"


class Greeter:
    """Greets people."""

    def run(self) -> str:
        return greet("world")
'''


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Return an initialised Database backed by a temp file."""
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture()
def indexer(db: Database) -> Indexer:
    loader = PluginLoader()
    loader.discover()
    return Indexer(db, loader, ContextRouterConfig(), REPO)


def _insert_polluted_rows(db: Database, junk_file: Path) -> int:
    """Simulate pre-v4.5 pollution: a symbol from an ignored dir + an edge."""
    cur = db.connection.execute(
        "INSERT INTO symbols (repo, file_path, name, kind, line_start, line_end,"
        " language, signature) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (REPO, str(junk_file), "junk_fn", "function", 1, 3, "python", "def junk_fn()"),
    )
    junk_id = cur.lastrowid
    assert junk_id is not None
    db.connection.execute(
        "INSERT INTO edges (repo, from_symbol_id, to_symbol_id, edge_type, weight)"
        " VALUES (?, ?, ?, ?, ?)",
        (REPO, junk_id, junk_id, "calls", 1.0),
    )
    db.connection.commit()
    return junk_id


def test_run_prunes_symbols_from_ignored_files(
    tmp_path: Path, db: Database, indexer: Indexer, capsys: pytest.CaptureFixture[str]
) -> None:
    """run() deletes symbols/edges from no-longer-eligible files, keeps valid ones."""
    # Repo layout: one valid file, one inside an ignored venv dir.
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(VALID_SOURCE)
    junk_dir = tmp_path / ".venv-crg"
    junk_dir.mkdir()
    junk_file = junk_dir / "junk.py"
    junk_file.write_text("def junk_fn():\n    return 1\n")

    junk_id = _insert_polluted_rows(db, junk_file)

    indexer.run(tmp_path)

    rows = db.connection.execute("SELECT file_path FROM symbols WHERE repo = ?", (REPO,)).fetchall()
    paths = [r[0] for r in rows]
    assert paths, "valid symbols must survive the prune"
    assert not any(".venv-crg" in p for p in paths), f"stale rows remain: {paths}"
    assert any(p.endswith("app/main.py") for p in paths)

    edge_count = db.connection.execute(
        "SELECT COUNT(*) FROM edges WHERE from_symbol_id = ? OR to_symbol_id = ?",
        (junk_id, junk_id),
    ).fetchone()[0]
    assert edge_count == 0, "edges referencing pruned symbols must be deleted"

    err = capsys.readouterr().err
    assert "Pruned 1 symbol file" in err


def test_run_prunes_nothing_and_stays_silent_when_db_is_clean(
    tmp_path: Path, db: Database, indexer: Indexer, capsys: pytest.CaptureFixture[str]
) -> None:
    """No stale rows -> no prune message (and valid symbols untouched)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text(VALID_SOURCE)

    indexer.run(tmp_path)

    count = db.connection.execute(
        "SELECT COUNT(*) FROM symbols WHERE repo = ?", (REPO,)
    ).fetchone()[0]
    assert count > 0
    assert "Pruned" not in capsys.readouterr().err


def test_run_incremental_does_not_prune(
    tmp_path: Path, db: Database, indexer: Indexer, capsys: pytest.CaptureFixture[str]
) -> None:
    """Incremental indexing sees only changed files and must never prune others."""
    (tmp_path / "app").mkdir()
    main_py = tmp_path / "app" / "main.py"
    main_py.write_text(VALID_SOURCE)
    junk_dir = tmp_path / ".venv-crg"
    junk_dir.mkdir()
    junk_file = junk_dir / "junk.py"
    junk_file.write_text("def junk_fn():\n    return 1\n")

    _insert_polluted_rows(db, junk_file)

    indexer.run_incremental([main_py])

    # The polluted row survives an incremental run — only a full run heals.
    stale = db.connection.execute(
        "SELECT COUNT(*) FROM symbols WHERE repo = ? AND file_path LIKE ?",
        (REPO, "%.venv-crg%"),
    ).fetchone()[0]
    assert stale == 1
    assert "Pruned" not in capsys.readouterr().err


def test_run_does_not_prune_when_no_files_eligible(
    tmp_path: Path, db: Database, indexer: Indexer, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero eligible files + populated index -> refuse to prune, warn instead.

    Guards against a broken environment (e.g. a JS-only repo indexed from an
    install that only ships the Python analyzer) wiping the whole index.
    """
    # Repo contains only a file with no registered analyzer.
    (tmp_path / "lib.nosuchext").write_text("function f() {}\n")

    _insert_polluted_rows(db, tmp_path / ".venv-crg" / "junk.py")

    indexer.run(tmp_path)

    count = db.connection.execute(
        "SELECT COUNT(*) FROM symbols WHERE repo = ?", (REPO,)
    ).fetchone()[0]
    assert count == 1, "existing symbols must survive when nothing is eligible"

    err = capsys.readouterr().err
    assert "WARN: skipping prune" in err
    assert "Pruned" not in err
