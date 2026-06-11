"""v4.6 A2 — scope-qualified symbol identity (DoD: v4.6-symbol-qualification).

Same-named symbols defined at different scopes in one file must be DISTINCT
symbols: N nested ``class Model(BaseModel)`` definitions inside N different
test functions index as N symbol rows with parent-chain-qualified identities
(``test_a.Model``), each carrying its own ``extends`` edge. The short
display name stays in ``symbols.name`` so retrieval by ``"Model"`` keeps
matching.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.config import ContextRouterConfig
from core.plugin_loader import PluginLoader
from graph_index.indexer import Indexer
from storage_sqlite.database import Database
from storage_sqlite.repositories import SymbolRepository

REPO = "test-repo"

NESTED_MODELS_SOURCE = '''"""Pydantic-style test module: same class name in many scopes."""


class BaseModel:
    """Stand-in base."""


def test_a():
    class Model(BaseModel):
        x: int = 1

    assert Model


def test_b():
    class Model(BaseModel):
        y: int = 2

    assert Model


def test_c():
    class Model(BaseModel):
        z: int = 3

    assert Model
'''

REDEFINED_FUNCTION_SOURCE = '''"""Module-level same-name redefinition (no parent scope to qualify)."""


def setup(x):
    return x


def setup(x):  # noqa: F811 — deliberate redefinition
    return x + 1
'''


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture()
def indexer(db: Database) -> Indexer:
    loader = PluginLoader()
    loader.discover()
    return Indexer(db, loader, ContextRouterConfig(), REPO)


def test_qualification_nested_same_named_classes_are_distinct(
    db: Database, indexer: Indexer, tmp_path: Path
) -> None:
    """N same-named nested classes -> N symbol rows, scope-qualified."""
    (tmp_path / "test_models.py").write_text(NESTED_MODELS_SOURCE)
    indexer.run(tmp_path)

    rows = db.connection.execute(
        "SELECT qualified_name FROM symbols WHERE repo = ? AND name = 'Model'"
        " ORDER BY line_start",
        (REPO,),
    ).fetchall()
    assert len(rows) == 3
    qualified = [r[0] for r in rows]
    assert qualified == ["test_a.Model", "test_b.Model", "test_c.Model"]


def test_qualification_each_definition_gets_its_own_extends_edge(
    db: Database, indexer: Indexer, tmp_path: Path
) -> None:
    """Each nested Model carries its own extends edge to BaseModel."""
    (tmp_path / "test_models.py").write_text(NESTED_MODELS_SOURCE)
    indexer.run(tmp_path)

    rows = db.connection.execute(
        """
        SELECT e.from_symbol_id, e.weight FROM edges e
        JOIN symbols f ON f.id = e.from_symbol_id
        JOIN symbols t ON t.id = e.to_symbol_id
        WHERE e.repo = ? AND e.edge_type = 'extends'
          AND f.name = 'Model' AND t.name = 'BaseModel'
        """,
        (REPO,),
    ).fetchall()
    # Three DISTINCT source symbols — not one collapsed source with the
    # occurrences flattened into a single row.
    assert len(rows) == 3
    assert len({r[0] for r in rows}) == 3
    assert all(r[1] == pytest.approx(1.0) for r in rows)


def test_qualification_short_name_retrieval_still_matches(
    db: Database, indexer: Indexer, tmp_path: Path
) -> None:
    """DoD negative case: lookup by the short name finds the symbols."""
    (tmp_path / "test_models.py").write_text(NESTED_MODELS_SOURCE)
    indexer.run(tmp_path)

    sym_repo = SymbolRepository(db.connection)
    # Cross-file by-name resolution still works on the short name.
    assert sym_repo.get_id_by_name(REPO, "Model") is not None
    # FTS retrieval by short name matches every definition.
    matches = [s for s in sym_repo.search_fts("Model", repo=REPO) if s.name == "Model"]
    assert len(matches) == 3


def test_qualification_module_level_collision_falls_back_to_line(
    db: Database, indexer: Indexer, tmp_path: Path
) -> None:
    """No parent chain available -> definition-line disambiguation, only
    for the colliding occurrences."""
    (tmp_path / "redefined.py").write_text(REDEFINED_FUNCTION_SOURCE)
    indexer.run(tmp_path)

    rows = db.connection.execute(
        "SELECT qualified_name, line_start FROM symbols"
        " WHERE repo = ? AND name = 'setup' ORDER BY line_start",
        (REPO,),
    ).fetchall()
    assert len(rows) == 2
    first, second = rows
    assert first["qualified_name"] == "setup"
    assert second["qualified_name"] == f"setup@{second['line_start']}"


def test_qualification_reindex_is_stable(
    db: Database, indexer: Indexer, tmp_path: Path
) -> None:
    """Re-indexing the same file reproduces the same qualified identities."""
    (tmp_path / "test_models.py").write_text(NESTED_MODELS_SOURCE)
    indexer.run(tmp_path)
    indexer.run(tmp_path)

    rows = db.connection.execute(
        "SELECT qualified_name FROM symbols WHERE repo = ? AND name = 'Model'"
        " ORDER BY line_start",
        (REPO,),
    ).fetchall()
    assert [r[0] for r in rows] == ["test_a.Model", "test_b.Model", "test_c.Model"]
