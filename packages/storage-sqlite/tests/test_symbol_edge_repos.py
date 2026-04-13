"""Tests for SymbolRepository and EdgeRepository — new methods added in Phase 9."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.interfaces import DependencyEdge, Symbol
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def _sym(name: str, kind: str = "function", file: str = "/src/app.py") -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        file=Path(file),
        line_start=1,
        line_end=5,
        language="python",
    )


class TestSymbolRepository:
    def test_add_returns_id(self, db: Database):
        repo = SymbolRepository(db.connection)
        sid = repo.add(_sym("foo"), "myrepo")
        assert isinstance(sid, int)
        assert sid > 0

    def test_get_id_by_name(self, db: Database):
        repo = SymbolRepository(db.connection)
        repo.add(_sym("bar"), "myrepo")
        sid = repo.get_id_by_name("myrepo", "bar")
        assert sid is not None

    def test_get_id(self, db: Database):
        repo = SymbolRepository(db.connection)
        repo.add(_sym("baz"), "myrepo")
        sid = repo.get_id("myrepo", "/src/app.py", "baz", "function")
        assert sid is not None

    def test_get_all(self, db: Database):
        repo = SymbolRepository(db.connection)
        repo.add(_sym("a"), "myrepo")
        repo.add(_sym("b"), "myrepo")
        all_syms = repo.get_all("myrepo")
        names = {s.name for s in all_syms}
        assert "a" in names
        assert "b" in names

    def test_update_community(self, db: Database):
        repo = SymbolRepository(db.connection)
        sid = repo.add(_sym("x"), "myrepo")
        repo.update_community("myrepo", sid, 42)
        all_syms = repo.get_all("myrepo")
        found = next(s for s in all_syms if s.name == "x")
        assert found.community_id == 42

    def test_get_communities(self, db: Database):
        repo = SymbolRepository(db.connection)
        s1 = repo.add(_sym("m1"), "myrepo")
        s2 = repo.add(_sym("m2"), "myrepo")
        repo.update_community("myrepo", s1, 0)
        repo.update_community("myrepo", s2, 0)
        communities = repo.get_communities("myrepo")
        assert 0 in communities
        assert set(communities[0]) == {s1, s2}

    def test_symbol_community_id_default_none(self, db: Database):
        repo = SymbolRepository(db.connection)
        repo.add(_sym("lone"), "myrepo")
        sym = repo.get_all("myrepo")[0]
        assert sym.community_id is None


class TestEdgeRepository:
    def test_add_raw_edge(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)

        s1 = sym_repo.add(_sym("p"), "r")
        s2 = sym_repo.add(_sym("q"), "r")
        edge_repo.add_raw("r", s1, s2, "calls")

        edges = edge_repo.get_all_edges("r")
        assert (s1, s2) in edges

    def test_add_bulk_resolves_names(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)

        sym_repo.add(_sym("alpha"), "r")
        sym_repo.add(_sym("beta"), "r")

        # Resolve IDs manually (matching how writer.py does it)
        alpha_id = sym_repo.get_id_by_name("r", "alpha")
        beta_id = sym_repo.get_id_by_name("r", "beta")
        dep = DependencyEdge(from_symbol="alpha", to_symbol="beta", edge_type="calls")
        edge_repo.add_bulk([(dep, alpha_id, beta_id)], "r")

        edges = edge_repo.get_all_edges("r")
        assert len(edges) == 1

    def test_add_bulk_skips_unresolved(self, db: Database):
        edge_repo = EdgeRepository(db.connection)
        # Empty resolved list — nothing to insert
        edge_repo.add_bulk([], "r")
        edges = edge_repo.get_all_edges("r")
        assert edges == []

    def test_get_all_edges_empty(self, db: Database):
        edge_repo = EdgeRepository(db.connection)
        edges = edge_repo.get_all_edges("nonexistent")
        assert edges == []
