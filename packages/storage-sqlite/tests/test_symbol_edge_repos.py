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
        sid_a = repo.add(_sym("a"), "myrepo")
        sid_b = repo.add(_sym("b"), "myrepo")
        all_syms = repo.get_all("myrepo")
        names = {s.name for s in all_syms}
        ids = {s.id for s in all_syms}
        assert "a" in names
        assert "b" in names
        assert ids == {sid_a, sid_b}

    def test_get_by_file_populates_symbol_ids(self, db: Database):
        repo = SymbolRepository(db.connection)
        sid = repo.add(_sym("only"), "myrepo")
        syms = repo.get_by_file("myrepo", "/src/app.py")
        assert len(syms) == 1
        assert syms[0].id == sid

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


class TestGetCallChainFiles:
    """Tests for EdgeRepository.get_call_chain_files (P5)."""

    def _seed_chain(self, db: Database) -> dict[str, int]:
        """Seed symbols and calls edges: a.py → b.py → c.py → d.py."""
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        repo = "chain_repo"

        a = sym_repo.add(_sym("func_a", file="/src/a.py"), repo)
        b = sym_repo.add(_sym("func_b", file="/src/b.py"), repo)
        c = sym_repo.add(_sym("func_c", file="/src/c.py"), repo)
        d = sym_repo.add(_sym("func_d", file="/src/d.py"), repo)

        edge_repo.add_raw(repo, a, b, "calls")
        edge_repo.add_raw(repo, b, c, "calls")
        edge_repo.add_raw(repo, c, d, "calls")

        return {"a": a, "b": b, "c": c, "d": d}

    def test_returns_direct_callee_at_depth_1(self, db: Database) -> None:
        self._seed_chain(db)
        edge_repo = EdgeRepository(db.connection)
        result = edge_repo.get_call_chain_files("chain_repo", "/src/a.py", max_depth=1)
        files = {f for f, _ in result}
        assert "/src/b.py" in files

    def test_depth_3_reaches_all_hops(self, db: Database) -> None:
        self._seed_chain(db)
        edge_repo = EdgeRepository(db.connection)
        result = edge_repo.get_call_chain_files("chain_repo", "/src/a.py", max_depth=3)
        files = {f for f, _ in result}
        assert "/src/b.py" in files
        assert "/src/c.py" in files
        assert "/src/d.py" in files

    def test_max_depth_limits_traversal(self, db: Database) -> None:
        self._seed_chain(db)
        edge_repo = EdgeRepository(db.connection)
        # depth=1 should NOT reach c.py or d.py
        result = edge_repo.get_call_chain_files("chain_repo", "/src/a.py", max_depth=1)
        files = {f for f, _ in result}
        assert "/src/c.py" not in files
        assert "/src/d.py" not in files

    def test_hop_depths_are_correct(self, db: Database) -> None:
        self._seed_chain(db)
        edge_repo = EdgeRepository(db.connection)
        result = dict(edge_repo.get_call_chain_files("chain_repo", "/src/a.py", max_depth=3))
        assert result.get("/src/b.py") == 1
        assert result.get("/src/c.py") == 2
        assert result.get("/src/d.py") == 3

    def test_cycle_does_not_loop_forever(self, db: Database) -> None:
        """A cycle in calls edges must not cause infinite traversal."""
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        repo = "cycle_repo"
        x = sym_repo.add(_sym("func_x", file="/src/x.py"), repo)
        y = sym_repo.add(_sym("func_y", file="/src/y.py"), repo)
        edge_repo.add_raw(repo, x, y, "calls")
        edge_repo.add_raw(repo, y, x, "calls")  # back-edge → cycle

        result = edge_repo.get_call_chain_files(repo, "/src/x.py", max_depth=10)
        files = {f for f, _ in result}
        assert "/src/y.py" in files
        # Crucially: no duplicate entries and terminates cleanly
        assert len(result) == len(set(f for f, _ in result))

    def test_empty_file_returns_empty(self, db: Database) -> None:
        edge_repo = EdgeRepository(db.connection)
        result = edge_repo.get_call_chain_files("no_repo", "/no/such/file.py")
        assert result == []

    def test_non_calls_edges_not_traversed(self, db: Database) -> None:
        """Only 'calls' edges should be walked, not 'imports' or 'tested_by'."""
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        repo = "import_repo"
        p = sym_repo.add(_sym("func_p", file="/src/p.py"), repo)
        q = sym_repo.add(_sym("func_q", file="/src/q.py"), repo)
        edge_repo.add_raw(repo, p, q, "imports")  # NOT 'calls'

        result = edge_repo.get_call_chain_files(repo, "/src/p.py", max_depth=3)
        assert result == []
