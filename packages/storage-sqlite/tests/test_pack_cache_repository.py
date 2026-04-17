"""Tests for PackCacheRepository (migration 0012)."""

from __future__ import annotations

from pathlib import Path

import pytest
from storage_sqlite.database import Database
from storage_sqlite.repositories import PackCacheRepository


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "pack_cache.db")
    database.initialize()
    return database


class TestPackCacheRepository:
    def test_put_then_get_returns_payload(self, db: Database) -> None:
        repo = PackCacheRepository(db.connection)
        repo.put("ck", "repo-a", '{"hello": "world"}', now=1_000.0)

        got = repo.get("ck", "repo-a", ttl_seconds=60.0, now=1_010.0)
        assert got == '{"hello": "world"}'

    def test_get_miss_returns_none(self, db: Database) -> None:
        repo = PackCacheRepository(db.connection)
        assert repo.get("missing", "repo-a", 60.0) is None

    def test_ttl_expired_returns_none(self, db: Database) -> None:
        repo = PackCacheRepository(db.connection)
        repo.put("ck", "repo-a", "payload", now=1_000.0)

        # t = 1_000 + 61 → 61s old > 60s TTL → miss
        got = repo.get("ck", "repo-a", ttl_seconds=60.0, now=1_061.0)
        assert got is None

    def test_put_replaces_existing(self, db: Database) -> None:
        repo = PackCacheRepository(db.connection)
        repo.put("ck", "repo-a", "first", now=1_000.0)
        repo.put("ck", "repo-a", "second", now=1_001.0)

        got = repo.get("ck", "repo-a", ttl_seconds=60.0, now=1_002.0)
        assert got == "second"

    def test_invalidate_repo_scoped(self, db: Database) -> None:
        repo = PackCacheRepository(db.connection)
        repo.put("ck1", "repo-a", "a1", now=1_000.0)
        repo.put("ck2", "repo-a", "a2", now=1_000.0)
        repo.put("ck1", "repo-b", "b1", now=1_000.0)

        deleted = repo.invalidate_repo("repo-a")
        assert deleted == 2
        assert repo.get("ck1", "repo-a", 60.0, now=1_001.0) is None
        assert repo.get("ck2", "repo-a", 60.0, now=1_001.0) is None
        assert repo.get("ck1", "repo-b", 60.0, now=1_001.0) == "b1"

    def test_invalidate_all(self, db: Database) -> None:
        repo = PackCacheRepository(db.connection)
        repo.put("ck", "repo-a", "x", now=1_000.0)
        repo.put("ck", "repo-b", "y", now=1_000.0)

        deleted = repo.invalidate_all()
        assert deleted == 2
        assert repo.get("ck", "repo-a", 60.0, now=1_001.0) is None
        assert repo.get("ck", "repo-b", 60.0, now=1_001.0) is None

    def test_different_repo_ids_isolate(self, db: Database) -> None:
        repo = PackCacheRepository(db.connection)
        repo.put("ck", "repo-v1", "old", now=1_000.0)
        # simulate a re-index: repo_id changed. old row is still there but
        # unreachable from the new repo_id.
        assert repo.get("ck", "repo-v2", 60.0, now=1_001.0) is None
        assert repo.get("ck", "repo-v1", 60.0, now=1_001.0) == "old"
