"""v4.6 B1 — indexer records freshness fingerprints (DoD: v4.6-pack-staleness-selfheal).

Every successfully indexed file gets a (mtime_ns, size) row: on full runs
(``run``), on the per-file incremental path (``run_incremental`` — used by
the watcher and ``update-index --file``), and on ``index_file``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from contracts.config import ContextRouterConfig
from core.plugin_loader import PluginLoader
from graph_index.indexer import Indexer
from storage_sqlite.database import Database
from storage_sqlite.repositories import FileFingerprintRepository

REPO = "test-repo"

SOURCE = '''"""Module."""


def alpha() -> int:
    """Return one."""
    return 1
'''


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "db" / "test.db")
    (tmp_path / "db").mkdir()
    database.initialize()
    return database


@pytest.fixture()
def indexer(db: Database) -> Indexer:
    loader = PluginLoader()
    loader.discover()
    return Indexer(db, loader, ContextRouterConfig(), REPO)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "alpha.py").write_text(SOURCE)
    (root / "beta.py").write_text(SOURCE.replace("alpha", "beta"))
    return root


def _expected_fp(path: Path) -> tuple[int, int]:
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


def test_staleness_full_run_records_fingerprints(
    indexer: Indexer, db: Database, project: Path
) -> None:
    indexer.run(project)
    stored = FileFingerprintRepository(db.connection).get_all(REPO)
    assert stored[str(project / "alpha.py")] == _expected_fp(project / "alpha.py")
    assert stored[str(project / "beta.py")] == _expected_fp(project / "beta.py")


def test_staleness_full_run_drops_fingerprints_of_removed_files(
    indexer: Indexer, db: Database, project: Path
) -> None:
    indexer.run(project)
    (project / "beta.py").unlink()
    indexer.run(project)
    stored = FileFingerprintRepository(db.connection).get_all(REPO)
    assert str(project / "beta.py") not in stored
    assert str(project / "alpha.py") in stored


def test_staleness_incremental_updates_fingerprint(
    indexer: Indexer, db: Database, project: Path
) -> None:
    indexer.run(project)
    target = project / "alpha.py"
    target.write_text(SOURCE + "\n# trailing comment\n")
    indexer.run_incremental([target])
    stored = FileFingerprintRepository(db.connection).get_all(REPO)
    assert stored[str(target)] == _expected_fp(target)


def test_staleness_incremental_deletes_fingerprint_for_removed_file(
    indexer: Indexer, db: Database, project: Path
) -> None:
    indexer.run(project)
    target = project / "beta.py"
    target.unlink()
    indexer.run_incremental([target])
    stored = FileFingerprintRepository(db.connection).get_all(REPO)
    assert str(target) not in stored


def test_staleness_index_file_records_fingerprint(
    indexer: Indexer, db: Database, project: Path
) -> None:
    target = project / "alpha.py"
    indexer.index_file(target)
    stored = FileFingerprintRepository(db.connection).get_all(REPO)
    assert stored[str(target)] == _expected_fp(target)
