"""Tests for graph_index.writer.SymbolWriter."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.interfaces import DependencyEdge, Symbol
from graph_index.writer import SymbolWriter
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


def _make_symbol(name: str, kind: str, file: Path) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        file=file,
        line_start=1,
        line_end=5,
        language="python",
        signature=f"def {name}()",
    )


def _make_edge(from_sym: str, to_sym: str) -> DependencyEdge:
    return DependencyEdge(from_symbol=from_sym, to_symbol=to_sym, edge_type="calls")


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Return an initialised in-memory Database."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    database.initialize()
    return database


def test_writer_stores_symbols(db: Database, tmp_path: Path) -> None:
    """SymbolWriter persists Symbol objects to the DB."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    file_path = tmp_path / "app.py"
    syms = [
        _make_symbol("hello", "function", file_path),
        _make_symbol("Greeter", "class", file_path),
    ]

    syms_written, edges_written = writer.write_file_results("test-repo", syms, file_path)

    assert syms_written == 2
    assert edges_written == 0

    stored = sym_repo.get_by_file("test-repo", str(file_path))
    names = {s.name for s in stored}
    assert "hello" in names
    assert "Greeter" in names


def test_writer_stores_resolvable_edges(db: Database, tmp_path: Path) -> None:
    """SymbolWriter stores edges when both endpoints are in the same file."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    file_path = tmp_path / "app.py"
    results: list[Symbol | DependencyEdge] = [
        _make_symbol("caller", "function", file_path),
        _make_symbol("callee", "function", file_path),
        _make_edge("caller", "callee"),
    ]

    syms_written, edges_written = writer.write_file_results("test-repo", results, file_path)

    assert syms_written == 2
    assert edges_written == 1
    assert edge_repo.count("test-repo") == 1


def test_writer_skips_unresolvable_edges(db: Database, tmp_path: Path) -> None:
    """SymbolWriter silently skips edges whose endpoints are in other files."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    file_path = tmp_path / "app.py"
    results: list[Symbol | DependencyEdge] = [
        _make_symbol("local_fn", "function", file_path),
        # Edge to a symbol that lives in a different file (not in results)
        _make_edge("local_fn", "external_fn"),
    ]

    syms_written, edges_written = writer.write_file_results("test-repo", results, file_path)

    assert syms_written == 1
    assert edges_written == 0
    assert edge_repo.count("test-repo") == 0


def test_writer_reindex_is_idempotent(db: Database, tmp_path: Path) -> None:
    """Calling write_file_results twice for same file gives same final count."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    file_path = tmp_path / "app.py"
    syms = [_make_symbol("fn_a", "function", file_path)]

    writer.write_file_results("test-repo", syms, file_path)
    writer.write_file_results("test-repo", syms, file_path)

    # Should not double-count
    assert sym_repo.count("test-repo") == 1


def test_writer_delete_by_file_cleans_up(db: Database, tmp_path: Path) -> None:
    """delete_by_file removes symbols written by the writer."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    file_path = tmp_path / "app.py"
    syms = [_make_symbol("fn_a", "function", file_path)]
    writer.write_file_results("test-repo", syms, file_path)

    assert sym_repo.count("test-repo") == 1

    sym_repo.delete_by_file("test-repo", str(file_path))
    assert sym_repo.count("test-repo") == 0
