"""Tests for storage-sqlite: Database, MigrationRunner, and repositories."""

from __future__ import annotations

from pathlib import Path

import pytest

from storage_sqlite.database import Database
from storage_sqlite.repositories import (
    DecisionRepository,
    ObservationRepository,
    RuntimeSignalRepository,
)
from contracts.models import Decision, Observation, RuntimeSignal


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Provide an initialized Database for each test."""
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


class TestDatabase:
    def test_schema_version_is_1_after_init(self, db: Database):
        row = db.connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
        assert row[0] == 6

    def test_initialize_is_idempotent(self, tmp_path: Path):
        database = Database(tmp_path / "idempotent.db")
        database.initialize()
        database.initialize()
        row = database.connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
        assert row[0] == 6
        database.close()

    def test_context_manager(self, tmp_path: Path):
        with Database(tmp_path / "ctx.db") as db:
            row = db.connection.execute("SELECT MAX(version) FROM schema_version").fetchone()
            assert row[0] == 6

    def test_connection_raises_before_initialize(self, tmp_path: Path):
        database = Database(tmp_path / "uninitialized.db")
        with pytest.raises(RuntimeError):
            _ = database.connection


class TestObservationRepository:
    def test_add_and_search_fts(self, db: Database):
        repo = ObservationRepository(db.connection)
        obs = Observation(summary="Fixed the null pointer exception in auth module")
        rowid = repo.add(obs)
        assert rowid > 0

        results = repo.search_fts("null pointer")
        assert len(results) == 1
        assert "null pointer" in results[0].summary

    def test_fts_returns_empty_for_no_match(self, db: Database):
        repo = ObservationRepository(db.connection)
        repo.add(Observation(summary="Fixed login timeout"))
        results = repo.search_fts("database migration")
        assert results == []


class TestDecisionRepository:
    def test_add_and_search_fts(self, db: Database):
        repo = DecisionRepository(db.connection)
        dec = Decision(
            title="Use SQLite for local storage",
            context="Need offline-capable storage with FTS support",
            decision="SQLite + FTS5 chosen over PostgreSQL",
        )
        returned_id = repo.add(dec)
        assert returned_id == dec.id

        results = repo.search_fts("SQLite")
        assert len(results) == 1
        assert results[0].title == "Use SQLite for local storage"

    def test_fts_searches_multiple_fields(self, db: Database):
        repo = DecisionRepository(db.connection)
        dec = Decision(
            title="Plugin architecture",
            context="Need extensible language support",
            decision="Use entry_points for plugin discovery",
        )
        repo.add(dec)
        # search on context field
        results = repo.search_fts("extensible")
        assert len(results) == 1


class TestRuntimeSignalRepository:
    def test_add_runtime_signal(self, db: Database):
        repo = RuntimeSignalRepository(db.connection)
        sig = RuntimeSignal(message="AttributeError: 'NoneType' object has no attribute 'split'")
        rowid = repo.add(sig)
        assert rowid > 0

        row = db.connection.execute(
            "SELECT message FROM runtime_signals WHERE id = ?", (rowid,)
        ).fetchone()
        assert "AttributeError" in row["message"]
