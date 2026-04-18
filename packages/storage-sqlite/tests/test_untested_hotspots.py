"""Tests for SymbolRepository.get_untested_hotspots and
EdgeRepository.count_by_type (added by P3 audit-untested-hotspots).

These tests exercise the storage layer only — the CLI wiring is covered
by ``apps/cli/tests/test_audit_cli.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol, SymbolRef
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def _sym(name: str, file: str = "/src/app.py") -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        file=Path(file),
        line_start=1,
        line_end=5,
        language="python",
    )


class TestCountByType:
    def test_returns_zero_for_empty_db(self, db: Database):
        assert EdgeRepository(db.connection).count_by_type("repo-x", "tested_by") == 0

    def test_counts_only_matching_type(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        a = sym_repo.add(_sym("a"), "r")
        b = sym_repo.add(_sym("b"), "r")
        edge_repo.add_raw("r", a, b, "calls")
        edge_repo.add_raw("r", a, b, "tested_by")
        edge_repo.add_raw("r", a, b, "tested_by")
        assert edge_repo.count_by_type("r", "calls") == 1
        assert edge_repo.count_by_type("r", "tested_by") == 2


class TestGetUntestedHotspots:
    def test_empty_db_returns_empty_list(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        assert sym_repo.get_untested_hotspots("r") == []

    def test_returns_symbolref_and_inbound(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        target = sym_repo.add(_sym("target"), "r")
        callers = [sym_repo.add(_sym(f"c{i}"), "r") for i in range(5)]
        for c in callers:
            edge_repo.add_raw("r", c, target, "calls")

        rows = sym_repo.get_untested_hotspots("r", top_pct=1.0)
        assert len(rows) == 1
        ref, inbound = rows[0]
        assert isinstance(ref, SymbolRef)
        assert ref.name == "target"
        assert inbound == 5

    def test_excludes_targets_with_tested_by(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        tested = sym_repo.add(_sym("tested"), "r")
        untested = sym_repo.add(_sym("untested"), "r")
        test_fn = sym_repo.add(_sym("test_tested"), "r")
        callers = [sym_repo.add(_sym(f"c{i}"), "r") for i in range(3)]
        for c in callers:
            edge_repo.add_raw("r", c, tested, "calls")
            edge_repo.add_raw("r", c, untested, "calls")
        edge_repo.add_raw("r", tested, test_fn, "tested_by")

        rows = sym_repo.get_untested_hotspots("r", top_pct=1.0)
        names = {ref.name for ref, _ in rows}
        assert "tested" not in names
        assert "untested" in names

    def test_includes_imports_as_inbound(self, db: Database):
        """``imports`` edges count toward the hub-score proxy alongside ``calls``."""
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        target = sym_repo.add(_sym("target"), "r")
        c1 = sym_repo.add(_sym("c1"), "r")
        c2 = sym_repo.add(_sym("c2"), "r")
        edge_repo.add_raw("r", c1, target, "imports")
        edge_repo.add_raw("r", c2, target, "calls")
        rows = sym_repo.get_untested_hotspots("r", top_pct=1.0)
        assert rows and rows[0][1] == 2

    def test_ignores_non_inbound_edge_types(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        target = sym_repo.add(_sym("target"), "r")
        c = sym_repo.add(_sym("c"), "r")
        # extends / implements should NOT count toward the inbound degree.
        edge_repo.add_raw("r", c, target, "extends")
        edge_repo.add_raw("r", c, target, "implements")
        rows = sym_repo.get_untested_hotspots("r", top_pct=1.0)
        assert rows == []

    def test_limit_cap_is_honoured(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        callers = [sym_repo.add(_sym(f"c{i}"), "r") for i in range(10)]
        targets = [sym_repo.add(_sym(f"t{i}"), "r") for i in range(10)]
        for c in callers:
            for t in targets:
                edge_repo.add_raw("r", c, t, "calls")

        rows = sym_repo.get_untested_hotspots("r", top_pct=1.0, limit_cap=3)
        assert len(rows) == 3

    def test_ordering_is_by_inbound_desc(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        high = sym_repo.add(_sym("high"), "r")
        low = sym_repo.add(_sym("low"), "r")
        callers = [sym_repo.add(_sym(f"c{i}"), "r") for i in range(5)]
        for c in callers:
            edge_repo.add_raw("r", c, high, "calls")
        edge_repo.add_raw("r", callers[0], low, "calls")

        rows = sym_repo.get_untested_hotspots("r", top_pct=1.0)
        names = [ref.name for ref, _ in rows]
        assert names.index("high") < names.index("low")

    def test_scoped_to_repo(self, db: Database):
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        a = sym_repo.add(_sym("a_target"), "repo-a")
        a_caller = sym_repo.add(_sym("a_caller"), "repo-a")
        edge_repo.add_raw("repo-a", a_caller, a, "calls")

        b = sym_repo.add(_sym("b_target"), "repo-b")
        b_caller = sym_repo.add(_sym("b_caller"), "repo-b")
        edge_repo.add_raw("repo-b", b_caller, b, "calls")

        rows_a = sym_repo.get_untested_hotspots("repo-a", top_pct=1.0)
        names_a = {ref.name for ref, _ in rows_a}
        assert names_a == {"a_target"}
