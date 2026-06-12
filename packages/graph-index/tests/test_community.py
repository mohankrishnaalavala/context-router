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


def _pin_get_all_cap_and_iter_all_batch(
    monkeypatch: pytest.MonkeyPatch, cap: int, batch_size: int
) -> None:
    """Simulate a >cap repo: get_all truncates at *cap*, iter_all pages small."""
    orig_get_all = SymbolRepository.get_all
    orig_iter_all = SymbolRepository.iter_all

    def capped_get_all(self, repo, limit=cap):
        return orig_get_all(self, repo, limit)

    def small_batch_iter_all(self, repo, batch_size=batch_size):
        return orig_iter_all(self, repo, batch_size=batch_size)

    monkeypatch.setattr(SymbolRepository, "get_all", capped_get_all)
    monkeypatch.setattr(SymbolRepository, "iter_all", small_batch_iter_all)


def test_getall_paging_communities_cover_full_symbol_set(
    repos, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """v4.6 A4 follow-up: community detection pages past the get_all cap.

    25 isolated symbols, get_all pinned to a 10-row cap, iter_all forced to
    page (batch_size=7 → 4 keyset pages). A capped consumer would label only
    10 symbols and WARN; iter_all must label all 25 silently.
    """
    sym_repo, edge_repo = repos
    repo = "big-repo"
    total, cap = 25, 10
    for i in range(total):
        sym_repo.add(_sym(f"node_{i}"), repo)

    _pin_get_all_cap_and_iter_all_batch(monkeypatch, cap=cap, batch_size=7)

    n = compute_communities(repo, sym_repo, edge_repo)

    captured = capsys.readouterr()
    assert "WARN: get_all" not in captured.err, (
        f"community detection still consumed capped get_all: {captured.err!r}"
    )
    # No edges → every symbol is its own community; a capped slice gives 10.
    assert n == total
    communities = sym_repo.get_communities(repo)
    assert sum(len(members) for members in communities.values()) == total
