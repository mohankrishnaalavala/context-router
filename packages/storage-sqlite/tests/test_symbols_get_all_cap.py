"""get_all must be deterministic and must warn when the cap truncates."""

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


def _sym(name: str) -> Symbol:
    return Symbol(
        name=name,
        kind="function",
        file=Path("/src/app.py"),
        line_start=1,
        line_end=5,
        language="python",
    )


def test_get_all_orders_by_id(db: Database) -> None:
    repo = SymbolRepository(db.connection)
    inserted_ids = [repo.add(_sym(f"sym_{i}"), "default") for i in range(5)]

    symbols = repo.get_all("default")

    assert [s.id for s in symbols] == inserted_ids
    assert [s.name for s in symbols] == [f"sym_{i}" for i in range(5)]


def test_get_all_warns_on_cap(db: Database, capsys: pytest.CaptureFixture[str]) -> None:
    repo = SymbolRepository(db.connection)
    for i in range(12):
        repo.add(_sym(f"sym_{i}"), "default")

    symbols = repo.get_all("default", limit=10)

    captured = capsys.readouterr()
    assert len(symbols) == 10
    assert "WARN" in captured.err
    assert "10" in captured.err


def test_get_all_no_warning_under_cap(
    db: Database, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = SymbolRepository(db.connection)
    for i in range(3):
        repo.add(_sym(f"sym_{i}"), "default")

    symbols = repo.get_all("default")

    captured = capsys.readouterr()
    assert len(symbols) == 3
    assert "WARN: get_all" not in captured.err
