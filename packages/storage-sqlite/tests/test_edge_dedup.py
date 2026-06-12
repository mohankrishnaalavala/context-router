"""v4.6 A1 — edge dedup with weight semantics (DoD: v4.6-edge-dedup).

Edges must be unique per (repo, from_symbol_id, to_symbol_id, edge_type).
Repeated occurrences become weight, not duplicate rows:

* Migration 0016 rebuilds ``edges`` with the UNIQUE constraint, collapsing
  pre-existing duplicates into one row with ``weight = SUM(weight)``.
* ``EdgeRepository.add_bulk`` pre-aggregates duplicates inside the batch
  (summing weights) and resolves cross-batch conflicts by REPLACING the
  stored weight (``DO UPDATE SET weight = excluded.weight``) so the
  delete-then-insert re-index path stays idempotent.
* Degree-based reads (``get_untested_hotspots``) consume SUM(weight),
  not raw row counts, so the collapsed signal is not flattened.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from contracts.interfaces import DependencyEdge, Symbol
from storage_sqlite.database import Database
from storage_sqlite.migrations import MigrationRunner
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

REPO = "test-repo"

_MIGRATIONS_DIR = (
    Path(__file__).parent.parent / "src" / "storage_sqlite" / "migrations"
)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Return an initialised Database backed by a temp file."""
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def _add_symbol(sym_repo: SymbolRepository, name: str, file: Path) -> int:
    return sym_repo.add(
        Symbol(
            name=name,
            kind="function",
            file=file,
            line_start=1,
            line_end=5,
            language="python",
        ),
        REPO,
    )


def _edge(edge_type: str = "calls", weight: float = 1.0) -> DependencyEdge:
    return DependencyEdge(
        from_symbol="a", to_symbol="b", edge_type=edge_type, weight=weight
    )


def _duplicate_groups(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT count(*) FROM (SELECT 1 FROM edges GROUP BY repo,"
        " from_symbol_id, to_symbol_id, edge_type HAVING COUNT(*) > 1)"
    ).fetchone()
    return int(row[0])


# ---------------------------------------------------------------------------
# Schema: unique constraint
# ---------------------------------------------------------------------------


def test_edges_unique_constraint_rejects_raw_duplicates(
    db: Database, tmp_path: Path
) -> None:
    """A raw second INSERT of the same (repo, from, to, type) must fail."""
    sym_repo = SymbolRepository(db.connection)
    fid = _add_symbol(sym_repo, "a", tmp_path / "a.py")
    tid = _add_symbol(sym_repo, "b", tmp_path / "a.py")

    db.connection.execute(
        "INSERT INTO edges (repo, from_symbol_id, to_symbol_id, edge_type, weight)"
        " VALUES (?, ?, ?, ?, 1.0)",
        (REPO, fid, tid, "calls"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.connection.execute(
            "INSERT INTO edges (repo, from_symbol_id, to_symbol_id, edge_type, weight)"
            " VALUES (?, ?, ?, ?, 1.0)",
            (REPO, fid, tid, "calls"),
        )


def test_migration_collapses_existing_duplicates_summing_weight(
    tmp_path: Path,
) -> None:
    """Upgrading a pre-0016 DB collapses duplicate edges into SUM(weight)."""
    # Build a DB at schema version 15 (one migration file short).
    partial_dir = tmp_path / "partial-migrations"
    partial_dir.mkdir()
    for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        if int(sql_file.stem.split("_")[0]) <= 15:
            shutil.copy(sql_file, partial_dir / sql_file.name)

    conn = sqlite3.connect(tmp_path / "old.db")
    conn.row_factory = sqlite3.Row
    runner = MigrationRunner(conn)
    runner.apply_all(partial_dir)
    assert runner.current_version() == 15

    conn.execute(
        "INSERT INTO symbols (repo, file_path, name, kind) VALUES (?, ?, ?, ?)",
        (REPO, "a.py", "a", "function"),
    )
    conn.execute(
        "INSERT INTO symbols (repo, file_path, name, kind) VALUES (?, ?, ?, ?)",
        (REPO, "a.py", "b", "function"),
    )
    fid, tid = (
        r[0]
        for r in conn.execute("SELECT id FROM symbols ORDER BY id").fetchall()
    )
    # 161 identical rows — the pydantic worst case.
    for _ in range(161):
        conn.execute(
            "INSERT INTO edges (repo, from_symbol_id, to_symbol_id, edge_type,"
            " weight) VALUES (?, ?, ?, ?, 1.0)",
            (REPO, fid, tid, "extends"),
        )
    conn.commit()

    # Apply the remaining migrations (0016+).
    runner.apply_all(_MIGRATIONS_DIR)

    rows = conn.execute(
        "SELECT weight FROM edges WHERE repo = ? AND from_symbol_id = ?"
        " AND to_symbol_id = ? AND edge_type = 'extends'",
        (REPO, fid, tid),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(161.0)
    assert _duplicate_groups(conn) == 0
    conn.close()


# ---------------------------------------------------------------------------
# add_bulk: in-batch aggregation + cross-batch replace
# ---------------------------------------------------------------------------


def test_add_bulk_aggregates_duplicates_into_weight(
    db: Database, tmp_path: Path
) -> None:
    """DoD negative case: 10 identical occurrences -> ONE row, weight >= 10."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    fid = _add_symbol(sym_repo, "a", tmp_path / "a.py")
    tid = _add_symbol(sym_repo, "b", tmp_path / "a.py")

    edge_repo.add_bulk([(_edge(), fid, tid)] * 10, REPO)

    rows = db.connection.execute(
        "SELECT weight FROM edges WHERE repo = ?", (REPO,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] >= 10.0


def test_add_bulk_reindex_is_idempotent_not_accumulating(
    db: Database, tmp_path: Path
) -> None:
    """Same batch twice == same DB state (replace, not weight += )."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    fid = _add_symbol(sym_repo, "a", tmp_path / "a.py")
    tid = _add_symbol(sym_repo, "b", tmp_path / "a.py")

    batch = [(_edge(), fid, tid)] * 10
    edge_repo.add_bulk(batch, REPO)
    edge_repo.add_bulk(batch, REPO)

    rows = db.connection.execute(
        "SELECT weight FROM edges WHERE repo = ?", (REPO,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(10.0)


def test_add_bulk_returns_unique_edge_count(db: Database, tmp_path: Path) -> None:
    """add_bulk reports the post-aggregation row count, not occurrences."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    fid = _add_symbol(sym_repo, "a", tmp_path / "a.py")
    tid = _add_symbol(sym_repo, "b", tmp_path / "a.py")
    other = _add_symbol(sym_repo, "c", tmp_path / "a.py")

    written = edge_repo.add_bulk(
        [(_edge(), fid, tid)] * 5 + [(_edge(), fid, other)],
        REPO,
    )
    assert written == 2


def test_add_single_edge_conflict_replaces_weight(
    db: Database, tmp_path: Path
) -> None:
    """EdgeRepository.add on an existing edge must not raise; it replaces."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    fid = _add_symbol(sym_repo, "a", tmp_path / "a.py")
    tid = _add_symbol(sym_repo, "b", tmp_path / "a.py")

    edge_repo.add(_edge(weight=1.0), REPO, fid, tid)
    edge_repo.add(_edge(weight=3.0), REPO, fid, tid)

    rows = db.connection.execute(
        "SELECT weight FROM edges WHERE repo = ?", (REPO,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# Degree reads consume weight, not row multiplicity
# ---------------------------------------------------------------------------


def test_untested_hotspots_degree_uses_edge_weight(
    db: Database, tmp_path: Path
) -> None:
    """Inbound degree ordering must follow SUM(weight), not COUNT(rows)."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    caller = _add_symbol(sym_repo, "caller", tmp_path / "a.py")
    hot = _add_symbol(sym_repo, "hot", tmp_path / "b.py")
    cold = _add_symbol(sym_repo, "cold", tmp_path / "c.py")

    # One row each — but `hot` carries the collapsed weight of 10 calls.
    edge_repo.add_bulk([(_edge(), caller, hot)] * 10, REPO)
    edge_repo.add_bulk([(_edge(), caller, cold)], REPO)

    hotspots = sym_repo.get_untested_hotspots(REPO, top_pct=1.0, limit_cap=10)
    by_name = {ref.name: inbound for ref, inbound in hotspots}
    assert by_name["hot"] == 10
    assert by_name["cold"] == 1
    # Ordering: weight-10 symbol first.
    assert hotspots[0][0].name == "hot"
