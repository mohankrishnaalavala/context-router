"""v4.6 A1 — end-to-end edge dedup through the writer (DoD: v4.6-edge-dedup).

DoD negative case: a real source file that calls the same function 10 times
must yield ONE stored edge row carrying weight >= 10 — collapsing rows must
not flatten the ranking signal, so hub scoring consumes weight too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.config import ContextRouterConfig
from contracts.interfaces import DependencyEdge, Symbol
from core.plugin_loader import PluginLoader
from graph_index.indexer import Indexer
from graph_index.metrics import compute_hub_scores
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

REPO = "test-repo"

REPEATED_CALLS_SOURCE = '''"""Module whose caller invokes helper ten times."""


def helper(n: int) -> int:
    """Return n."""
    return n


def caller() -> int:
    """Call helper ten times."""
    total = 0
    total += helper(1)
    total += helper(2)
    total += helper(3)
    total += helper(4)
    total += helper(5)
    total += helper(6)
    total += helper(7)
    total += helper(8)
    total += helper(9)
    total += helper(10)
    return total
'''


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture()
def indexer(db: Database) -> Indexer:
    loader = PluginLoader()
    loader.discover()
    return Indexer(db, loader, ContextRouterConfig(), REPO)


def test_ten_calls_yield_one_edge_row_with_weight_ten(
    db: Database, indexer: Indexer, tmp_path: Path
) -> None:
    """DoD negative case: 10 calls -> ONE edge row, weight >= 10."""
    src = tmp_path / "repeated.py"
    src.write_text(REPEATED_CALLS_SOURCE)

    indexer.run(tmp_path)

    rows = db.connection.execute(
        """
        SELECT e.weight FROM edges e
        JOIN symbols f ON f.id = e.from_symbol_id
        JOIN symbols t ON t.id = e.to_symbol_id
        WHERE e.repo = ? AND e.edge_type = 'calls'
          AND f.name = 'caller' AND t.name = 'helper'
        """,
        (REPO,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] >= 10.0


def test_full_index_has_zero_duplicate_edge_groups(
    db: Database, indexer: Indexer, tmp_path: Path
) -> None:
    """The DoD duplicate-edge query must return 0 after indexing."""
    (tmp_path / "repeated.py").write_text(REPEATED_CALLS_SOURCE)
    indexer.run(tmp_path)
    indexer.run(tmp_path)  # re-index must stay clean too

    row = db.connection.execute(
        "SELECT count(*) FROM (SELECT 1 FROM edges GROUP BY repo,"
        " from_symbol_id, to_symbol_id, edge_type HAVING COUNT(*) > 1)"
    ).fetchone()
    assert row[0] == 0


def test_reindex_keeps_same_edge_state(
    db: Database, indexer: Indexer, tmp_path: Path
) -> None:
    """Same input twice == same DB state (weights must not accumulate)."""
    (tmp_path / "repeated.py").write_text(REPEATED_CALLS_SOURCE)
    indexer.run(tmp_path)
    first = db.connection.execute(
        "SELECT from_symbol_id, to_symbol_id, edge_type, weight FROM edges"
        " WHERE repo = ? ORDER BY edge_type, weight",
        (REPO,),
    ).fetchall()
    indexer.run(tmp_path)
    second = db.connection.execute(
        "SELECT from_symbol_id, to_symbol_id, edge_type, weight FROM edges"
        " WHERE repo = ? ORDER BY edge_type, weight",
        (REPO,),
    ).fetchall()
    assert [tuple(r)[2:] for r in first] == [tuple(r)[2:] for r in second]
    assert len(first) == len(second)


def test_hub_scores_consume_weight_not_row_count(db: Database) -> None:
    """A single weight-10 edge must outrank ten weight-1 rows' worth."""
    conn = db.connection
    sym_repo = SymbolRepository(conn)
    edge_repo = EdgeRepository(conn)

    def _sym(name: str) -> Symbol:
        return Symbol(
            name=name,
            kind="function",
            file=Path("/src/app.py"),
            line_start=1,
            line_end=2,
            language="python",
        )

    caller = sym_repo.add(_sym("caller"), REPO)
    heavy = sym_repo.add(_sym("heavy"), REPO)
    light = sym_repo.add(_sym("light"), REPO)

    edge = DependencyEdge(from_symbol="caller", to_symbol="heavy", edge_type="calls")
    edge_repo.add_bulk([(edge, caller, heavy)] * 10, REPO)
    light_edge = DependencyEdge(
        from_symbol="caller", to_symbol="light", edge_type="calls"
    )
    edge_repo.add_bulk([(light_edge, caller, light)], REPO)

    scores = compute_hub_scores(conn, REPO)
    assert scores[heavy] == pytest.approx(1.0)
    assert scores[light] == pytest.approx(0.1)
