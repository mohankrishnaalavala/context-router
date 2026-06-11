"""v4.6 A2 — schema side of symbol qualification (DoD: v4.6-symbol-qualification).

Migration 0017 adds ``symbols.qualified_name`` and discards every cached
pack: symbol identity churn invalidates ``pack_cache`` (migration 0012),
and a stale cache must be discarded loudly — with a named stderr WARN —
never served.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from contracts.interfaces import Symbol
from storage_sqlite.database import Database
from storage_sqlite.migrations import MigrationRunner
from storage_sqlite.repositories import SymbolRepository

REPO = "test-repo"

_MIGRATIONS_DIR = (
    Path(__file__).parent.parent / "src" / "storage_sqlite" / "migrations"
)


def _connect_at_version(tmp_path: Path, version: int) -> sqlite3.Connection:
    """Return a connection migrated only up to *version*."""
    partial_dir = tmp_path / f"migrations-up-to-{version}"
    partial_dir.mkdir()
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        if int(sql_file.stem.split("_")[0]) <= version:
            shutil.copy(sql_file, partial_dir / sql_file.name)
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.row_factory = sqlite3.Row
    MigrationRunner(conn).apply_all(partial_dir)
    return conn


def test_qualified_name_column_persisted_and_read_back(tmp_path: Path) -> None:
    """add/add_bulk store qualified_name; readers surface it."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    sym_repo = SymbolRepository(db.connection)

    nested = Symbol(
        name="Model",
        kind="class",
        file=tmp_path / "test_models.py",
        line_start=10,
        line_end=12,
        language="python",
        qualified_name="test_a.Model",
    )
    sym_repo.add_bulk([nested], REPO)

    stored = sym_repo.get_by_file(REPO, str(tmp_path / "test_models.py"))
    assert len(stored) == 1
    assert stored[0].name == "Model"
    assert stored[0].qualified_name == "test_a.Model"


def test_qualified_name_defaults_to_short_name(tmp_path: Path) -> None:
    """A symbol without explicit qualification keeps name as identity."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    sym_repo = SymbolRepository(db.connection)

    sym_repo.add(
        Symbol(
            name="helper",
            kind="function",
            file=tmp_path / "a.py",
            line_start=1,
            line_end=2,
            language="python",
        ),
        REPO,
    )
    stored = sym_repo.get_by_file(REPO, str(tmp_path / "a.py"))
    assert stored[0].qualified_name == "helper"


def test_migration_0017_discards_stale_pack_cache_with_warn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Upgrading past 0016 purges pack_cache and WARNs with a named reason."""
    conn = _connect_at_version(tmp_path, 16)
    conn.execute(
        "INSERT INTO pack_cache (cache_key, repo_id, pack_json, inserted_at)"
        " VALUES ('k', 'r', '{}', ?)",
        (time.time(),),
    )
    conn.commit()

    MigrationRunner(conn).apply_all(_MIGRATIONS_DIR)

    rows = conn.execute("SELECT count(*) FROM pack_cache").fetchone()
    assert rows[0] == 0

    err = capsys.readouterr().err
    assert "WARN" in err
    assert "pack cache" in err.lower() or "pack_cache" in err.lower()
    conn.close()


def test_fresh_database_initializes_without_migration_warn(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A brand-new DB has no stale caches — no upgrade WARN noise."""
    db = Database(tmp_path / "fresh.db")
    db.initialize()
    err = capsys.readouterr().err
    assert "WARN" not in err
