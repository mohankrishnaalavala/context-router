"""Tests for v3 phase4/edge-source-resolution-fix (writer side).

Four invariants pinned:

1. ``extends`` edges anchor on the class row, never the constructor.
2. ``implements`` edges anchor on the class row, never the constructor.
3. ``tested_by`` source anchoring prefers class over constructor rows.
4. When neither a class nor a constructor row can be resolved, the
   writer emits a stderr debug note (CLAUDE.md silent-failure rule)
   and does NOT store a bogus edge.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import DependencyEdge, Symbol
from graph_index.writer import SymbolWriter
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Return an initialised on-disk SQLite database."""
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    database.initialize()
    return database


def _class_and_constructor(
    name: str, file_path: Path
) -> list[Symbol]:
    """Seed a class + a constructor with the same name in one file.

    This is the shape that triggered the v2 bug: the symbols table has
    a row for the class AND a row for the constructor, both named
    ``UserService``.  The pre-fix resolver picked whichever appeared
    first in ``id_map`` (typically the constructor, because constructor
    rows persist into ``id_map`` under the plain name when ``id_map``
    used last-write-wins semantics).
    """
    return [
        Symbol(
            name=name, kind="class", file=file_path,
            line_start=1, line_end=20, language="csharp",
            signature=f"class {name}",
        ),
        Symbol(
            name=name, kind="constructor", file=file_path,
            line_start=5, line_end=9, language="csharp",
            signature=f"public {name}()",
        ),
    ]


def _get_row_for_edge(
    conn, repo: str, edge_type: str
) -> tuple[int, str] | None:
    """Return (from_symbol_id, kind_of_that_row) for the first edge of *edge_type*."""
    cur = conn.execute(
        """
        SELECT e.from_symbol_id, s.kind AS from_kind
        FROM edges e
        JOIN symbols s ON s.id = e.from_symbol_id
        WHERE e.repo = ? AND e.edge_type = ?
        LIMIT 1
        """,
        (repo, edge_type),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return (row["from_symbol_id"], row["from_kind"])


# ---------------------------------------------------------------------------
# 1. extends anchors on class, not constructor.
# ---------------------------------------------------------------------------


def test_extends_edge_anchors_on_class_not_constructor(
    db: Database, tmp_path: Path
) -> None:
    """A seeded class + constructor pair must not misdirect an
    ``extends`` edge onto the constructor row.

    Shape: ``UsersController`` (class) and ``UsersController``
    (constructor) both live at the same file.  The analyzer emits
    ``extends`` with ``from_symbol='UsersController'``.  The writer's
    resolver MUST pick the class row.
    """
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    repo = "edge-src-repo"
    file_path = tmp_path / "UsersController.cs"

    symbols = _class_and_constructor("UsersController", file_path)
    # Parent class in a different file.
    parent_file = tmp_path / "ControllerBase.cs"
    symbols.append(
        Symbol(
            name="ControllerBase", kind="class", file=parent_file,
            line_start=1, line_end=5, language="csharp",
            signature="class ControllerBase",
        )
    )
    # extends edge keyed by class NAME (the analyzer-emitted shape).
    edge = DependencyEdge(
        from_symbol="UsersController",
        to_symbol="ControllerBase",
        edge_type="extends",
    )

    # Seed parent class first (different file).
    sym_repo.add(symbols[2], repo)
    # Write the subclass file — this is the unit under test.
    writer.write_file_results(repo, symbols[:2] + [edge], file_path)

    got = _get_row_for_edge(db.connection, repo, "extends")
    assert got is not None, "extends edge was dropped"
    from_id, from_kind = got
    assert from_kind == "class", (
        f"extends edge anchored on kind={from_kind!r}; "
        f"must be 'class' (constructor-anchored edges are the bug)"
    )

    # Double-check the `id` matches the class row, not the constructor.
    expected_class_id = db.connection.execute(
        "SELECT id FROM symbols WHERE repo=? AND name=? AND kind='class' "
        "AND file_path=?",
        (repo, "UsersController", str(file_path)),
    ).fetchone()["id"]
    assert from_id == expected_class_id


# ---------------------------------------------------------------------------
# 2. implements anchors on class, not constructor.
# ---------------------------------------------------------------------------


def test_implements_edge_anchors_on_class_not_constructor(
    db: Database, tmp_path: Path
) -> None:
    """Same invariant for ``implements``: class row wins over constructor."""
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    repo = "edge-src-repo"
    file_path = tmp_path / "UserService.cs"

    symbols = _class_and_constructor("UserService", file_path)
    iface_file = tmp_path / "IUserService.cs"
    symbols.append(
        Symbol(
            name="IUserService", kind="interface", file=iface_file,
            line_start=1, line_end=5, language="csharp",
            signature="interface IUserService",
        )
    )
    edge = DependencyEdge(
        from_symbol="UserService",
        to_symbol="IUserService",
        edge_type="implements",
    )

    sym_repo.add(symbols[2], repo)
    writer.write_file_results(repo, symbols[:2] + [edge], file_path)

    got = _get_row_for_edge(db.connection, repo, "implements")
    assert got is not None, "implements edge was dropped"
    _, from_kind = got
    assert from_kind == "class", (
        f"implements edge anchored on kind={from_kind!r}; "
        f"must be 'class' (constructor-anchored edges are the bug)"
    )


# ---------------------------------------------------------------------------
# 3. tested_by source prefers class over constructor.
# ---------------------------------------------------------------------------


def test_tested_by_source_prefers_class_over_constructor(
    db: Database, tmp_path: Path
) -> None:
    """The C# analyzer emits ``tested_by`` edges with the SUT *class
    name* as ``from_symbol``.  If the SUT file also declares a
    same-named constructor, the writer MUST prefer the class row.

    Why this matters: constructor-anchored ``tested_by`` edges would
    make the coverage-audit query (``SELECT COUNT(*) FROM edges WHERE
    edge_type='tested_by' GROUP BY from_kind``) credit constructors as
    if they were tested, hiding genuinely-untested classes.
    """
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    repo = "edge-src-repo"
    sut_file = tmp_path / "UserService.cs"
    test_file = tmp_path / "UserServiceTests.cs"

    sut_symbols = _class_and_constructor("UserService", sut_file)
    test_sym = Symbol(
        name="TestFoo", kind="method", file=test_file,
        line_start=3, line_end=5, language="csharp",
        signature="public async Task TestFoo()",
    )

    # Seed SUT first — exercises the cross-file resolver path for
    # tested_by (SUT lives in a different file than the test class).
    sym_repo.add(sut_symbols[0], repo)  # class
    sym_repo.add(sut_symbols[1], repo)  # constructor

    # Now write the test file — this is the unit under test.  Edge
    # keyed by the SUT class NAME (what the analyzer emits).
    edge = DependencyEdge(
        from_symbol="UserService",
        to_symbol="TestFoo",
        edge_type="tested_by",
    )
    writer.write_file_results(repo, [test_sym, edge], test_file)

    got = _get_row_for_edge(db.connection, repo, "tested_by")
    assert got is not None, "tested_by edge was dropped"
    _, from_kind = got
    assert from_kind == "class", (
        f"tested_by source anchored on kind={from_kind!r}; "
        f"must be 'class' so coverage queries see the SUT row"
    )


# ---------------------------------------------------------------------------
# 4. Unresolved inheritance edges log to stderr and drop the edge.
# ---------------------------------------------------------------------------


def test_writer_logs_unresolved_inheritance_edge(
    db: Database, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When neither class nor constructor rows exist for the source of
    an inheritance edge, the writer MUST:
      - NOT insert an edge.
      - print a debug note to stderr that names the symbol + edge kind
        (CLAUDE.md silent-failure rule).
    """
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    writer = SymbolWriter(sym_repo, edge_repo)

    repo = "edge-src-repo"
    file_path = tmp_path / "Dangling.cs"

    # Only the parent exists; the source class is not indexed.
    parent = Symbol(
        name="ControllerBase", kind="class", file=tmp_path / "ControllerBase.cs",
        line_start=1, line_end=5, language="csharp",
        signature="class ControllerBase",
    )
    sym_repo.add(parent, repo)

    # No source symbol for 'DanglingController' is written.
    edge = DependencyEdge(
        from_symbol="DanglingController",
        to_symbol="ControllerBase",
        edge_type="extends",
    )

    # Flush captured output buffer so prior noise doesn't muddle the
    # assertion.
    capsys.readouterr()

    syms_written, edges_written = writer.write_file_results(
        repo, [edge], file_path
    )

    assert syms_written == 0
    assert edges_written == 0, (
        "unresolved inheritance source must NOT create an edge"
    )

    err = capsys.readouterr().err
    # The debug line names both the symbol and the edge kind so an
    # operator can grep for mis-resolutions in CI logs.
    assert "DanglingController" in err, (
        f"expected stderr to name the unresolved symbol; got:\n{err}"
    )
    assert "extends" in err, (
        f"expected stderr to name the edge kind; got:\n{err}"
    )

    # Regression guard: the edges table stays empty for this test.
    count = db.connection.execute(
        "SELECT COUNT(*) FROM edges WHERE repo=? AND edge_type='extends'",
        (repo,),
    ).fetchone()[0]
    assert count == 0
