"""Regression tests for v3.1 `hub-bridge-sqlite-reuse` (P2).

The ranker's hub/bridge boost used to open a fresh `sqlite3.Connection`
per `rank()` call, causing connection-lifetime churn on large repos
where the Orchestrator already holds an open `Database`. This module
pins the new contract:

1. When a `db_connection` is supplied, the boost MUST NOT call
   `sqlite3.connect()` during `rank()`.
2. When no `db_connection` is supplied (ranker used standalone), the
   fallback path still opens a fresh connection and works unchanged
   (regression guard — the negative case from the registry entry).
3. The shared connection is NOT closed by the ranker — caller owns it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from contracts.interfaces import Symbol
from contracts.models import ContextItem
from ranking.ranker import ContextRanker
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

# ---------------------------------------------------------------------------
# Fixtures — a minimal hub/leaf layout matching `test_hub_boost.py`.
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / ".context-router").mkdir(parents=True)
    (root / "src").mkdir()
    return root


@pytest.fixture()
def seeded_db(project_root: Path):
    hub_path = project_root / "src" / "hub.py"
    leaf_path = project_root / "src" / "leaf.py"
    hub_path.write_text("def hub(items):\n    return items\n")
    leaf_path.write_text("def leaf(items):\n    return items\n")

    db_path = project_root / ".context-router" / "context-router.db"
    db = Database(db_path)
    db.initialize()
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    repo = "default"

    sym_repo.add(
        Symbol(
            name="hub",
            kind="function",
            file=hub_path,
            line_start=1,
            line_end=2,
            language="python",
        ),
        repo,
    )
    sym_repo.add(
        Symbol(
            name="leaf",
            kind="function",
            file=leaf_path,
            line_start=1,
            line_end=2,
            language="python",
        ),
        repo,
    )
    for i in range(6):
        sym_repo.add(
            Symbol(
                name=f"caller{i}",
                kind="function",
                file=project_root / "src" / f"c{i}.py",
                line_start=1,
                line_end=2,
                language="python",
            ),
            repo,
        )

    hub_id = sym_repo.get_id_by_name(repo, "hub")
    leaf_id = sym_repo.get_id_by_name(repo, "leaf")
    assert hub_id is not None and leaf_id is not None
    for i in range(6):
        cid = sym_repo.get_id_by_name(repo, f"caller{i}")
        edge_repo.add_raw(repo, cid, hub_id, "calls")
    edge_repo.add_raw(
        repo, sym_repo.get_id_by_name(repo, "caller0"), leaf_id, "calls"
    )
    yield db
    db.close()


def _item(*, title: str, path: Path, confidence: float = 0.5) -> ContextItem:
    return ContextItem(
        source_type="file",
        repo="default",
        path_or_ref=str(path),
        title=title,
        excerpt="rank items for ingestion pipeline",
        reason="",
        confidence=confidence,
        est_tokens=100,
    )


# ---------------------------------------------------------------------------
# (1) Injected connection is reused — no fresh `sqlite3.connect()`.
# ---------------------------------------------------------------------------


def test_hub_boost_reuses_injected_connection(project_root: Path, seeded_db) -> None:
    """A ranker built with `db_connection=...` must NOT open a new connection.

    This is the core guarantee of `hub-bridge-sqlite-reuse`: when the
    Orchestrator passes its open connection in, `rank()` triggers zero
    `sqlite3.connect()` invocations.
    """
    items = [
        _item(title="hub", path=project_root / "src" / "hub.py", confidence=0.5),
        _item(title="leaf", path=project_root / "src" / "leaf.py", confidence=0.5),
    ]
    # use_embeddings=False isolates the hub-boost connection-reuse contract
    # from the semantic-boost path which legitimately opens its own
    # read-only connection to look up the persistent embeddings table.
    ranker = ContextRanker(
        token_budget=0,
        use_embeddings=False,
        use_hub_boost=True,
        db_connection=seeded_db.connection,
    )

    # Spy AFTER the fixture is set up — we only want to count connects
    # that happen during rank(), not the fixture's own open().
    with patch("sqlite3.connect", wraps=sqlite3.connect) as spy:
        ranked = ranker.rank(items, "rank items for ingestion pipeline", "implement")

    assert spy.call_count == 0, (
        f"expected 0 sqlite3.connect calls during rank(), got {spy.call_count}"
    )
    # Sanity: the boost still took effect — hub outranks leaf.
    titles = [i.title for i in ranked]
    assert titles[0] == "hub", f"expected hub first, got {titles}"


def test_hub_boost_does_not_close_injected_connection(
    project_root: Path, seeded_db
) -> None:
    """Caller owns the connection. The ranker must not close it.

    We verify by running a second rank() call on the same ranker +
    connection and confirming no errors and the boost still works.
    """
    items = [
        _item(title="hub", path=project_root / "src" / "hub.py", confidence=0.5),
        _item(title="leaf", path=project_root / "src" / "leaf.py", confidence=0.5),
    ]
    # use_embeddings=False isolates the hub-boost connection-reuse contract
    # from the semantic-boost path which legitimately opens its own
    # read-only connection to look up the persistent embeddings table.
    ranker = ContextRanker(
        token_budget=0,
        use_embeddings=False,
        use_hub_boost=True,
        db_connection=seeded_db.connection,
    )
    _first = ranker.rank(list(items), "q", "implement")
    second = ranker.rank(list(items), "q", "implement")
    # Connection still usable — a simple query must succeed.
    row = seeded_db.connection.execute("SELECT 1").fetchone()
    assert row[0] == 1
    # Boost still effective.
    assert second[0].title == "hub"


# ---------------------------------------------------------------------------
# (2) Fallback path — no `db_connection` → still opens a fresh connection.
# ---------------------------------------------------------------------------


def test_hub_boost_falls_back_to_fresh_connection_when_no_db_passed(
    project_root: Path, seeded_db
) -> None:
    """Standalone ranker (no `db_connection`) still works via the old path.

    Negative-case guard: we mustn't regress existing callers (tests,
    scripts) that construct the ranker without an injected connection.
    """
    items = [
        _item(title="hub", path=project_root / "src" / "hub.py", confidence=0.5),
        _item(title="leaf", path=project_root / "src" / "leaf.py", confidence=0.5),
    ]
    ranker = ContextRanker(token_budget=0, use_hub_boost=True)

    # In the fallback path, the ranker DOES open a fresh connection — at
    # least one (may be more if _resolve_symbol_ids also opens one).
    # v4.4: hub_boost is gated to handover mode only.
    with patch("sqlite3.connect", wraps=sqlite3.connect) as spy:
        ranked = ranker.rank(items, "rank items", "handover")

    assert spy.call_count >= 1, (
        "fallback path must still open sqlite3 connections when no "
        "db_connection is supplied"
    )
    assert ranked[0].title == "hub", f"boost must still work; got {[i.title for i in ranked]}"
