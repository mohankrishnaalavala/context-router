"""v4.6 A3 — edge-count reporting consistency (DoD: v4.6-edge-count-consistency).

The edge count an indexing run reports must equal the rows the database
stores: ``reported == SELECT count(*) FROM edges WHERE repo = ?`` after a
full run AND after an immediate re-run (pydantic previously reported
24,718 / 27,915 across runs while storing 24,253). The incremental
(watcher) path reports a per-file delta that matches the stored rows for
that file — a mismatch is a test failure, never a silently logged number.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.config import ContextRouterConfig
from core.plugin_loader import PluginLoader
from graph_index.indexer import Indexer
from storage_sqlite.database import Database

REPO = "test-repo"

# Two modules with cross-file references plus a test module: enough edge
# variety (calls, imports, extends, tested_by) to expose drift between
# "edges emitted/resolved" and "edge rows stored".
HELPERS_SOURCE = '''"""Helpers module."""


class Base:
    """Base class."""


def helper(n: int) -> int:
    """Return n."""
    return n
'''

APP_SOURCE = '''"""App module importing helpers cross-file."""

from helpers import Base, helper


class Widget(Base):
    """A widget."""

    def render(self) -> int:
        return helper(1) + helper(2) + helper(3)


def run() -> int:
    return helper(4)
'''

TEST_SOURCE = '''"""Tests for app."""

from app import run


def test_run():
    assert run() == 4
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


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "helpers.py").write_text(HELPERS_SOURCE)
    (tmp_path / "app.py").write_text(APP_SOURCE)
    (tmp_path / "test_app.py").write_text(TEST_SOURCE)
    return tmp_path


def _stored_edges(db: Database) -> int:
    row = db.connection.execute(
        "SELECT count(*) FROM edges WHERE repo = ?", (REPO,)
    ).fetchone()
    return int(row[0])


def test_edge_count_reported_equals_stored_after_full_index(
    db: Database, indexer: Indexer, project: Path
) -> None:
    result = indexer.run(project)
    assert result.edges_written == _stored_edges(db)
    assert result.edges_written > 0


def test_edge_count_reported_equals_stored_after_immediate_rerun(
    db: Database, indexer: Indexer, project: Path
) -> None:
    """reported == stored on every run, and re-runs reach a steady state.

    Note: run 1 and run 2 may legitimately store different edge sets on
    cross-file fixtures (re-indexing a file cascade-deletes edges into its
    old symbol rows — a pre-existing resolution-order limitation, not a
    reporting bug). A3's contract is that the REPORTED number never lies
    about storage, which is asserted at every step.
    """
    first = indexer.run(project)
    assert first.edges_written == _stored_edges(db)
    second = indexer.run(project)
    assert second.edges_written == _stored_edges(db)
    third = indexer.run(project)
    assert third.edges_written == _stored_edges(db)
    # Steady state: an immediate re-run of an already-converged index
    # reports the identical count.
    assert third.edges_written == second.edges_written


def test_edge_count_incremental_delta_matches_stored_rows(
    db: Database, indexer: Indexer, project: Path
) -> None:
    """Watcher path: the per-file delta equals the rows stored for that
    file, and re-running the same update changes nothing."""
    indexer.run(project)

    result = indexer.run_incremental([project / "app.py"])

    stored_for_file = db.connection.execute(
        """
        SELECT count(*) FROM edges
        WHERE repo = ? AND from_symbol_id IN (
            SELECT id FROM symbols WHERE repo = ? AND file_path = ?
        )
        """,
        (REPO, REPO, str(project / "app.py")),
    ).fetchone()[0]
    assert result.edges_written == stored_for_file
    assert result.edges_written > 0
    total_after_first = _stored_edges(db)

    # Idempotent: re-running the identical incremental update reports the
    # same delta and leaves the stored total unchanged.
    again = indexer.run_incremental([project / "app.py"])
    assert again.edges_written == result.edges_written
    assert _stored_edges(db) == total_after_first
