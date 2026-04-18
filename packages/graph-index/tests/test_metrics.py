"""Unit tests for ``graph_index.metrics`` — hub and bridge scores."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from contracts.interfaces import Symbol
from graph_index.metrics import compute_bridge_scores, compute_hub_scores
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


@pytest.fixture()
def db(tmp_path: Path):
    db = Database(tmp_path / "metrics.db")
    db.initialize()
    yield db
    db.close()


def _sym(name: str, file_path: str = "/src/app.py") -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        file=Path(file_path),
        line_start=1,
        line_end=2,
        language="python",
    )


# ---------------------------------------------------------------------------
# compute_hub_scores
# ---------------------------------------------------------------------------


def test_hub_scores_empty_db_returns_empty(db) -> None:
    assert compute_hub_scores(db.connection, "missing-repo") == {}


def test_hub_scores_none_connection_returns_empty() -> None:
    assert compute_hub_scores(None, "anything") == {}


def test_hub_scores_normalised_by_repo_max(db) -> None:
    """Degree-N hub should score 1.0; degree-1 should score 1/N."""
    conn = db.connection
    sym_repo = SymbolRepository(conn)
    edge_repo = EdgeRepository(conn)
    repo = "hub-test"

    sym_repo.add(_sym("hub"), repo)
    sym_repo.add(_sym("leaf"), repo)
    for caller in ("a", "b", "c", "d", "e", "f"):
        sym_repo.add(_sym(caller), repo)

    hub_id = sym_repo.get_id_by_name(repo, "hub")
    leaf_id = sym_repo.get_id_by_name(repo, "leaf")
    caller_ids = [sym_repo.get_id_by_name(repo, c) for c in "abcdef"]

    # 6 inbound calls into `hub`
    for cid in caller_ids:
        edge_repo.add_raw(repo, cid, hub_id, "calls")
    # 1 inbound edge into `leaf`
    edge_repo.add_raw(repo, caller_ids[0], leaf_id, "calls")

    scores = compute_hub_scores(conn, repo)
    assert scores[hub_id] == pytest.approx(1.0)
    assert scores[leaf_id] == pytest.approx(1.0 / 6)
    # Callers themselves receive no inbound edges → absent from result
    for cid in caller_ids:
        assert cid not in scores


def test_hub_scores_include_inheritance_edges(db) -> None:
    """``extends`` and ``implements`` edges from #48 count toward the hub signal."""
    conn = db.connection
    sym_repo = SymbolRepository(conn)
    edge_repo = EdgeRepository(conn)
    repo = "inherit"

    sym_repo.add(_sym("Base"), repo)
    sym_repo.add(_sym("Child1"), repo)
    sym_repo.add(_sym("Child2"), repo)

    base = sym_repo.get_id_by_name(repo, "Base")
    c1 = sym_repo.get_id_by_name(repo, "Child1")
    c2 = sym_repo.get_id_by_name(repo, "Child2")

    edge_repo.add_raw(repo, c1, base, "extends")
    edge_repo.add_raw(repo, c2, base, "implements")

    scores = compute_hub_scores(conn, repo)
    # Base is the unique inbound target → top-score.
    assert scores[base] == pytest.approx(1.0)


def test_hub_scores_ignores_unknown_edge_kinds(db) -> None:
    """Only calls/imports/extends/implements are counted — ``tested_by`` is noise here."""
    conn = db.connection
    sym_repo = SymbolRepository(conn)
    edge_repo = EdgeRepository(conn)
    repo = "filter"

    sym_repo.add(_sym("subject"), repo)
    sym_repo.add(_sym("tester"), repo)
    subj = sym_repo.get_id_by_name(repo, "subject")
    test = sym_repo.get_id_by_name(repo, "tester")
    edge_repo.add_raw(repo, test, subj, "tested_by")
    assert compute_hub_scores(conn, repo) == {}


def test_hub_scores_scopes_by_repo(db) -> None:
    """An edge in repo A must not inflate scores in repo B."""
    conn = db.connection
    sym_repo = SymbolRepository(conn)
    edge_repo = EdgeRepository(conn)

    sym_repo.add(_sym("x", "/r1/x.py"), "r1")
    sym_repo.add(_sym("y", "/r1/y.py"), "r1")
    x1 = sym_repo.get_id_by_name("r1", "x")
    y1 = sym_repo.get_id_by_name("r1", "y")
    edge_repo.add_raw("r1", x1, y1, "calls")

    assert compute_hub_scores(conn, "r2") == {}


def test_hub_scores_handles_missing_tables_gracefully() -> None:
    """A connection to a blank DB should return ``{}`` rather than raise."""
    conn = sqlite3.connect(":memory:")
    try:
        assert compute_hub_scores(conn, "any") == {}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# compute_bridge_scores
# ---------------------------------------------------------------------------


def test_bridge_scores_none_connection_returns_empty() -> None:
    assert compute_bridge_scores(None, "any") == {}


def test_bridge_scores_counts_distinct_communities(db) -> None:
    """A source that reaches 3 communities scores 1.0; a source hitting
    2 communities scores 2/3 on a repo whose max is 3."""
    conn = db.connection
    sym_repo = SymbolRepository(conn)
    edge_repo = EdgeRepository(conn)
    repo = "bridge"

    sym_repo.add(_sym("src"), repo)
    sym_repo.add(_sym("other_src"), repo)
    sym_repo.add(_sym("t1"), repo)
    sym_repo.add(_sym("t2"), repo)
    sym_repo.add(_sym("t3"), repo)

    src = sym_repo.get_id_by_name(repo, "src")
    other = sym_repo.get_id_by_name(repo, "other_src")
    t1 = sym_repo.get_id_by_name(repo, "t1")
    t2 = sym_repo.get_id_by_name(repo, "t2")
    t3 = sym_repo.get_id_by_name(repo, "t3")

    # Assign communities: t1→0, t2→1, t3→2
    sym_repo.update_community(repo, t1, 0)
    sym_repo.update_community(repo, t2, 1)
    sym_repo.update_community(repo, t3, 2)
    sym_repo.update_community(repo, src, 99)  # src's own community irrelevant
    sym_repo.update_community(repo, other, 99)

    # `src` reaches 3 distinct communities; `other_src` reaches 2.
    edge_repo.add_raw(repo, src, t1, "calls")
    edge_repo.add_raw(repo, src, t2, "calls")
    edge_repo.add_raw(repo, src, t3, "imports")
    edge_repo.add_raw(repo, other, t1, "calls")
    edge_repo.add_raw(repo, other, t2, "calls")

    scores = compute_bridge_scores(conn, repo)
    assert scores[src] == pytest.approx(1.0)
    assert scores[other] == pytest.approx(2.0 / 3)


def test_bridge_scores_excludes_single_community_sources(db) -> None:
    """A symbol whose outbound calls land in one community is not a bridge."""
    conn = db.connection
    sym_repo = SymbolRepository(conn)
    edge_repo = EdgeRepository(conn)
    repo = "single-comm"

    sym_repo.add(_sym("src"), repo)
    sym_repo.add(_sym("t1"), repo)
    sym_repo.add(_sym("t2"), repo)
    src = sym_repo.get_id_by_name(repo, "src")
    t1 = sym_repo.get_id_by_name(repo, "t1")
    t2 = sym_repo.get_id_by_name(repo, "t2")
    sym_repo.update_community(repo, src, 0)
    sym_repo.update_community(repo, t1, 1)
    sym_repo.update_community(repo, t2, 1)

    edge_repo.add_raw(repo, src, t1, "calls")
    edge_repo.add_raw(repo, src, t2, "calls")

    assert compute_bridge_scores(conn, repo) == {}


def test_bridge_scores_skip_null_community_targets(db) -> None:
    """Edges to symbols with NULL community_id must be ignored."""
    conn = db.connection
    sym_repo = SymbolRepository(conn)
    edge_repo = EdgeRepository(conn)
    repo = "null-comm"

    sym_repo.add(_sym("src"), repo)
    sym_repo.add(_sym("unset1"), repo)
    sym_repo.add(_sym("unset2"), repo)
    src = sym_repo.get_id_by_name(repo, "src")
    u1 = sym_repo.get_id_by_name(repo, "unset1")
    u2 = sym_repo.get_id_by_name(repo, "unset2")
    # Intentionally DO NOT set community_id on the targets.
    edge_repo.add_raw(repo, src, u1, "calls")
    edge_repo.add_raw(repo, src, u2, "calls")
    assert compute_bridge_scores(conn, repo) == {}


def test_bridge_scores_handles_missing_tables_gracefully() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        assert compute_bridge_scores(conn, "any") == {}
    finally:
        conn.close()
