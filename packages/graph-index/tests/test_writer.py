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


# ---------------------------------------------------------------------------
# v3 phase3/edge-kinds-extended: writer must materialize external inheritance
# targets so extends/implements edges survive for framework base types.
# ---------------------------------------------------------------------------


def test_writer_materializes_external_extends_target(
    db: Database, tmp_path: Path
) -> None:
    """``class Dog extends Animal`` where ``Animal`` is NOT in-project:
    writer materializes an ``external`` symbol stub and stores the edge."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    file_path = tmp_path / "Dog.java"
    sym = Symbol(
        name="Dog", kind="class", file=file_path,
        line_start=1, line_end=10, language="java", signature="class Dog",
    )
    edge = DependencyEdge(from_symbol="Dog", to_symbol="Animal", edge_type="extends")

    written_syms, written_edges = writer.write_file_results(
        "test-repo", [sym, edge], file_path
    )
    assert written_syms == 1
    assert written_edges == 1  # the extends edge is NOT dropped
    # An "external" stub was created for Animal.
    ext_id = sym_repo.get_id_by_name("test-repo", "Animal")
    assert ext_id is not None


def test_writer_materializes_external_implements_target(
    db: Database, tmp_path: Path
) -> None:
    """``class Foo implements Bar`` where ``Bar`` is external: same stub
    materialization path as extends."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    file_path = tmp_path / "Foo.java"
    sym = Symbol(
        name="Foo", kind="class", file=file_path,
        line_start=1, line_end=5, language="java", signature="class Foo",
    )
    edge = DependencyEdge(
        from_symbol="Foo", to_symbol="Serializable", edge_type="implements"
    )
    _, written_edges = writer.write_file_results(
        "test-repo", [sym, edge], file_path
    )
    assert written_edges == 1


def test_writer_does_not_materialize_for_calls_edges(
    db: Database, tmp_path: Path
) -> None:
    """Regression: ``calls`` edges with unresolvable targets stay strict —
    no external stubs created, edge is dropped.  Only inheritance edges
    get the fallback so the graph doesn't fill with phantom call nodes."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    file_path = tmp_path / "app.py"
    sym = _make_symbol("caller", "function", file_path)
    edge = DependencyEdge(
        from_symbol="caller", to_symbol="external_unknown_fn",
        edge_type="calls",
    )
    _, written_edges = writer.write_file_results(
        "test-repo", [sym, edge], file_path
    )
    assert written_edges == 0
    # No external stub for the unresolved callee.
    assert sym_repo.get_id_by_name("test-repo", "external_unknown_fn") is None


def test_writer_reuses_external_stub_across_edges(
    db: Database, tmp_path: Path
) -> None:
    """When multiple files extend the same external type, the stub is
    created once and reused — no duplicate ``external`` symbol rows."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    # First file
    f1 = tmp_path / "Dog.java"
    s1 = Symbol(
        name="Dog", kind="class", file=f1,
        line_start=1, line_end=5, language="java", signature="class Dog",
    )
    e1 = DependencyEdge(from_symbol="Dog", to_symbol="Animal", edge_type="extends")
    writer.write_file_results("test-repo", [s1, e1], f1)

    # Second file, same external target
    f2 = tmp_path / "Cat.java"
    s2 = Symbol(
        name="Cat", kind="class", file=f2,
        line_start=1, line_end=5, language="java", signature="class Cat",
    )
    e2 = DependencyEdge(from_symbol="Cat", to_symbol="Animal", edge_type="extends")
    writer.write_file_results("test-repo", [s2, e2], f2)

    # Exactly one "Animal" stub exists, no duplicates.
    conn = db.connection
    row = conn.execute(
        "SELECT count(*) FROM symbols WHERE repo=? AND name=? AND kind='external'",
        ("test-repo", "Animal"),
    ).fetchone()
    assert row[0] == 1
