"""iter_all must page the full symbol set without a cap (v4.6 A4).

DoD ``v4.6-getall-paging``: ``iter_all`` is the internal-pipeline API —
keyset pagination, no row cap, no WARN. ``get_all`` keeps its 10k cap and
loud stderr WARN for external consumers, and the WARN now points callers
at ``iter_all``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from storage_sqlite.database import Database
from storage_sqlite.repositories import SymbolRepository


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def _sym(name: str, qualified_name: str = "") -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        file=Path("/src/app.py"),
        line_start=1,
        line_end=5,
        language="python",
        signature=f"def {name}() -> None",
        docstring=f"doc for {name}",
        qualified_name=qualified_name,
    )


def test_iter_all_pages_across_batch_boundaries(db: Database) -> None:
    """12 symbols with batch_size=5 → three keyset pages, all 12 rows, in id order."""
    repo = SymbolRepository(db.connection)
    inserted_ids = [repo.add(_sym(f"sym_{i}"), "default") for i in range(12)]

    symbols = list(repo.iter_all("default", batch_size=5))

    assert [s.id for s in symbols] == inserted_ids
    assert [s.name for s in symbols] == [f"sym_{i}" for i in range(12)]
    assert len({s.id for s in symbols}) == 12  # all distinct, no page overlap


def test_iter_all_empty_repo_yields_nothing(db: Database) -> None:
    repo = SymbolRepository(db.connection)
    assert list(repo.iter_all("default")) == []


def test_iter_all_has_no_cap_and_no_warn(
    db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    """iter_all returns rows past any batch boundary and never warns."""
    repo = SymbolRepository(db.connection)
    for i in range(12):
        repo.add(_sym(f"sym_{i}"), "default")

    symbols = list(repo.iter_all("default", batch_size=5))

    captured = capsys.readouterr()
    assert len(symbols) == 12
    assert "WARN" not in captured.err


def test_iter_all_returns_same_symbol_shape_as_get_all(db: Database) -> None:
    """Every field — including qualified_name (migration 0017) — matches get_all."""
    repo = SymbolRepository(db.connection)
    repo.add(_sym("plain"), "default")
    repo.add(_sym("method_a", qualified_name="MyClass.method_a"), "default")

    via_get_all = repo.get_all("default")
    via_iter_all = list(repo.iter_all("default", batch_size=1))

    assert via_iter_all == via_get_all
    assert via_iter_all[1].qualified_name == "MyClass.method_a"
    assert via_iter_all[0].qualified_name == "plain"  # COALESCE fallback shape


def test_getall_paging_cap_warn_suggests_iter_all(
    db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    """Negative case: get_all at the cap still WARNs loudly and names iter_all."""
    repo = SymbolRepository(db.connection)
    for i in range(12):
        repo.add(_sym(f"sym_{i}"), "default")

    symbols = repo.get_all("default", limit=10)

    captured = capsys.readouterr()
    assert len(symbols) == 10
    assert "WARN" in captured.err
    assert "iter_all" in captured.err
