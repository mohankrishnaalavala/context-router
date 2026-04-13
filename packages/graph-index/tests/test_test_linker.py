"""Tests for the test_linker post-processing pass."""

from __future__ import annotations

from pathlib import Path

import pytest

from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository
from contracts.interfaces import Symbol
from graph_index.test_linker import link_tests


@pytest.fixture()
def db(tmp_path: Path):
    """Provide an initialized in-memory-style Database."""
    db = Database(tmp_path / "test.db")
    db.initialize()
    yield db
    db.close()


@pytest.fixture()
def repos(db):
    """Provide SymbolRepository and EdgeRepository sharing the same connection."""
    conn = db.connection
    return SymbolRepository(conn), EdgeRepository(conn)


def _make_symbol(name: str, kind: str, file_path: str) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        file=Path(file_path),
        line_start=1,
        line_end=5,
        language="python",
    )


def test_link_tests_emits_tested_by_edges(repos):
    """test_process should produce a tested_by edge pointing at process."""
    sym_repo, edge_repo = repos
    repo = "test-repo"

    sym_repo.add(_make_symbol("process", "function", "/src/app.py"), repo)
    sym_repo.add(_make_symbol("test_process", "function", "/tests/test_app.py"), repo)

    count = link_tests(repo, sym_repo, edge_repo)
    assert count >= 1

    edges = edge_repo.get_all_edges(repo)
    assert len(edges) >= 1


def test_link_tests_no_match_returns_zero(repos):
    """When no test function matches a source symbol, count should be 0."""
    sym_repo, edge_repo = repos
    repo = "test-repo"

    sym_repo.add(_make_symbol("compute", "function", "/src/math.py"), repo)
    sym_repo.add(_make_symbol("test_unrelated", "function", "/tests/test_math.py"), repo)

    count = link_tests(repo, sym_repo, edge_repo)
    assert count == 0


def test_link_tests_skips_test_to_test(repos):
    """Should not create edges where the source symbol is itself a test."""
    sym_repo, edge_repo = repos
    repo = "test-repo"

    # Both in test files
    sym_repo.add(_make_symbol("test_foo", "function", "/tests/test_a.py"), repo)
    sym_repo.add(_make_symbol("test_test_foo", "function", "/tests/test_b.py"), repo)

    count = link_tests(repo, sym_repo, edge_repo)
    # test_test_foo would look for symbol "test_foo" but "test_foo" is in a test file
    assert count == 0


def test_link_tests_multiple_matches(repos):
    """Multiple test functions can link to multiple source symbols."""
    sym_repo, edge_repo = repos
    repo = "test-repo"

    sym_repo.add(_make_symbol("alpha", "function", "/src/utils.py"), repo)
    sym_repo.add(_make_symbol("beta", "function", "/src/utils.py"), repo)
    sym_repo.add(_make_symbol("test_alpha", "function", "/tests/test_utils.py"), repo)
    sym_repo.add(_make_symbol("test_beta", "function", "/tests/test_utils.py"), repo)

    count = link_tests(repo, sym_repo, edge_repo)
    assert count == 2
