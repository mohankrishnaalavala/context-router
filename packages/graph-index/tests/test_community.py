"""Tests for the community detection pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.interfaces import Symbol
from graph_index.community import compute_communities
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


@pytest.fixture()
def db(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.initialize()
    yield db
    db.close()


@pytest.fixture()
def repos(db):
    conn = db.connection
    return SymbolRepository(conn), EdgeRepository(conn)


def _sym(name: str, file_path: str = "/src/app.py") -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        file=Path(file_path),
        line_start=1,
        line_end=2,
        language="python",
    )


def test_compute_communities_single_component(repos):
    """All symbols connected by edges should share a community_id."""
    sym_repo, edge_repo = repos
    repo = "myrepo"

    sym_repo.add(_sym("a"), repo)
    sym_repo.add(_sym("b"), repo)
    sym_repo.add(_sym("c"), repo)

    a_id = sym_repo.get_id_by_name(repo, "a")
    b_id = sym_repo.get_id_by_name(repo, "b")
    c_id = sym_repo.get_id_by_name(repo, "c")

    edge_repo.add_raw(repo, a_id, b_id, "calls")
    edge_repo.add_raw(repo, b_id, c_id, "calls")

    n = compute_communities(repo, sym_repo, edge_repo)
    assert n == 1

    communities = sym_repo.get_communities(repo)
    assert len(communities) == 1
    members = list(communities.values())[0]
    assert set(members) == {a_id, b_id, c_id}


def test_compute_communities_two_components(repos):
    """Disconnected symbols should receive different community ids."""
    sym_repo, edge_repo = repos
    repo = "myrepo"

    sym_repo.add(_sym("x"), repo)
    sym_repo.add(_sym("y"), repo)
    sym_repo.add(_sym("p"), repo)
    sym_repo.add(_sym("q"), repo)

    x_id = sym_repo.get_id_by_name(repo, "x")
    y_id = sym_repo.get_id_by_name(repo, "y")
    p_id = sym_repo.get_id_by_name(repo, "p")
    q_id = sym_repo.get_id_by_name(repo, "q")

    edge_repo.add_raw(repo, x_id, y_id, "calls")
    edge_repo.add_raw(repo, p_id, q_id, "calls")

    n = compute_communities(repo, sym_repo, edge_repo)
    assert n == 2

    communities = sym_repo.get_communities(repo)
    assert len(communities) == 2


def test_compute_communities_no_symbols(repos):
    """Empty repo returns 0 communities."""
    sym_repo, edge_repo = repos
    n = compute_communities("empty-repo", sym_repo, edge_repo)
    assert n == 0


def test_compute_communities_isolated_symbols(repos):
    """Symbols with no edges each form their own community."""
    sym_repo, edge_repo = repos
    repo = "iso"

    sym_repo.add(_sym("lone1"), repo)
    sym_repo.add(_sym("lone2"), repo)
    sym_repo.add(_sym("lone3"), repo)

    n = compute_communities(repo, sym_repo, edge_repo)
    assert n == 3
