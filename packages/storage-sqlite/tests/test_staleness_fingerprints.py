"""v4.6 B1 — file_fingerprints storage (DoD: v4.6-pack-staleness-selfheal).

Migration 0018 stores one (mtime_ns, size) row per indexed file so the
orchestrator can detect stale files at pack time with one batched read.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from storage_sqlite.database import Database
from storage_sqlite.repositories import FileFingerprintRepository

REPO = "test-repo"


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture()
def fp_repo(db: Database) -> FileFingerprintRepository:
    return FileFingerprintRepository(db.connection)


def test_staleness_migration_creates_fingerprint_table(db: Database) -> None:
    row = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name='file_fingerprints'"
    ).fetchone()
    assert row is not None


def test_staleness_fingerprint_upsert_and_get_all(
    fp_repo: FileFingerprintRepository,
) -> None:
    fp_repo.upsert(REPO, "/src/a.py", 111, 10)
    fp_repo.upsert(REPO, "/src/b.py", 222, 20)
    assert fp_repo.get_all(REPO) == {
        "/src/a.py": (111, 10),
        "/src/b.py": (222, 20),
    }
    # Upsert replaces, never duplicates.
    fp_repo.upsert(REPO, "/src/a.py", 333, 30)
    assert fp_repo.get_all(REPO)["/src/a.py"] == (333, 30)
    assert fp_repo.count(REPO) == 2


def test_staleness_fingerprint_replace_all_drops_removed_files(
    fp_repo: FileFingerprintRepository,
) -> None:
    fp_repo.upsert(REPO, "/src/old.py", 1, 1)
    fp_repo.replace_all(REPO, {"/src/new.py": (2, 2)})
    assert fp_repo.get_all(REPO) == {"/src/new.py": (2, 2)}


def test_staleness_fingerprint_delete_and_repo_isolation(
    fp_repo: FileFingerprintRepository,
) -> None:
    fp_repo.upsert(REPO, "/src/a.py", 1, 1)
    fp_repo.upsert("other-repo", "/src/a.py", 9, 9)
    fp_repo.delete(REPO, "/src/a.py")
    assert fp_repo.count(REPO) == 0
    # Rows in other repos are untouched by delete and replace_all.
    fp_repo.replace_all(REPO, {})
    assert fp_repo.get_all("other-repo") == {"/src/a.py": (9, 9)}
