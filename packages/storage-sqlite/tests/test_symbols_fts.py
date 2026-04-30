"""Tests for migration 0015 (symbols_fts) and SymbolRepository.search_fts.

Phase 4 of v4.4.4: FTS5-anchored implement-mode candidate retrieval. The
migration adds an external-content FTS5 virtual table over
``(name, signature, file_path)`` plus three triggers keeping it in sync,
and the repository exposes a BM25-ranked ``search_fts`` method consumed
by the orchestrator when no diff anchor is available.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from storage_sqlite.database import Database
from storage_sqlite.migrations import MigrationRunner
from storage_sqlite.repositories import SymbolRepository

_MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "storage_sqlite" / "migrations"


def _sym(
    name: str,
    *,
    kind: str = "function",
    file: str = "/src/app.py",
    signature: str = "",
    docstring: str = "",
) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        file=Path(file),
        line_start=1,
        line_end=10,
        language="python",
        signature=signature,
        docstring=docstring,
    )


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "fts.db")
    database.initialize()
    return database


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestSymbolsFtsMigration:
    """Schema-level checks for migration 0015."""

    def test_symbols_fts_table_exists(self, db: Database) -> None:
        row = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='symbols_fts'"
        ).fetchone()
        assert row is not None, "symbols_fts virtual table missing after migration"

    def test_triggers_exist(self, db: Database) -> None:
        rows = db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND name IN ('symbols_ai', 'symbols_ad', 'symbols_au')"
        ).fetchall()
        names = {row["name"] for row in rows}
        assert names == {"symbols_ai", "symbols_ad", "symbols_au"}

    def test_insert_trigger_mirrors_into_fts(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        repo.add(
            _sym("unprepareResources", signature="def unprepareResources(self):"),
            "k8s",
        )
        # The FTS5 unicode61 tokenizer case-folds; quote the camelCase
        # identifier so the match doesn't treat it as a bareword that's
        # been lowered to "unprepareresources".
        rows = db.connection.execute(
            "SELECT name FROM symbols_fts WHERE symbols_fts MATCH '\"unprepareResources\"'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["name"] == "unprepareResources"

    def test_update_trigger_replaces_fts_row(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        sid = repo.add(_sym("oldname"), "k8s")
        db.connection.execute(
            "UPDATE symbols SET name = 'newname' WHERE id = ?", (sid,)
        )
        db.connection.commit()

        old = db.connection.execute(
            "SELECT count(*) AS c FROM symbols_fts WHERE name MATCH 'oldname'"
        ).fetchone()
        new = db.connection.execute(
            "SELECT count(*) AS c FROM symbols_fts WHERE name MATCH 'newname'"
        ).fetchone()
        assert old["c"] == 0
        assert new["c"] == 1

    def test_delete_trigger_removes_fts_row(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        sid = repo.add(_sym("ephemeral"), "k8s")
        db.connection.execute("DELETE FROM symbols WHERE id = ?", (sid,))
        db.connection.commit()
        rows = db.connection.execute(
            "SELECT count(*) AS c FROM symbols_fts WHERE name MATCH 'ephemeral'"
        ).fetchone()
        assert rows["c"] == 0

    def test_seed_from_existing_rows(self, tmp_path: Path) -> None:
        """A pre-existing DB at version 14 (no symbols_fts) gets seeded on upgrade."""
        db_path = tmp_path / "preexisting.db"
        # Manually initialise to schema_version 14 by running migrations 0001..0014.
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        for sql_file in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            version = int(sql_file.stem.split("_")[0])
            if version > 14:
                continue
            conn.executescript(sql_file.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR REPLACE INTO schema_version(version) VALUES (?)",
                (version,),
            )
        # Insert a row before symbols_fts exists — it must show up after upgrade.
        conn.execute(
            "INSERT INTO symbols (repo, file_path, name, kind, line_start, line_end,"
            " language, signature) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "k8s",
                "/pkg/manager.go",
                "preExisting",
                "function",
                1,
                10,
                "go",
                "func preExisting()",
            ),
        )
        conn.commit()

        # Now apply remaining migrations including 0015.
        MigrationRunner(conn).apply_all(_MIGRATIONS_DIR)

        # The FTS5 unicode61 tokenizer case-folds, so the query must be
        # quoted (or lowered) to match the original mixed-case identifier.
        rows = conn.execute(
            "SELECT name FROM symbols_fts WHERE symbols_fts MATCH '\"preExisting\"'"
        ).fetchall()
        assert len(rows) == 1
        # Sanity: the symbols base table still has the row, and the FTS row
        # references it by rowid (so JOINs back to symbols.id work).
        joined = conn.execute(
            "SELECT s.name FROM symbols s JOIN symbols_fts f ON s.id = f.rowid"
        ).fetchall()
        assert [r["name"] for r in joined] == ["preExisting"]
        conn.close()


# ---------------------------------------------------------------------------
# search_fts tests
# ---------------------------------------------------------------------------


class TestSearchFts:
    def test_empty_query_returns_empty_list(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        repo.add(_sym("foo"), "k8s")
        assert repo.search_fts("") == []
        assert repo.search_fts("   ") == []

    def test_basic_match(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        repo.add(
            _sym(
                "unprepareResources",
                signature="def unprepareResources(self, claimRef):",
                file="/pkg/kubelet/cm/dra/manager.go",
            ),
            "k8s",
        )
        repo.add(_sym("unrelated_helper"), "k8s")
        results = repo.search_fts("unprepareResources", repo="k8s")
        assert len(results) == 1
        assert results[0].name == "unprepareResources"

    def test_match_via_signature(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        repo.add(
            _sym(
                "do_thing",
                signature="def do_thing(claimRef: ClaimRef) -> None: ...",
            ),
            "k8s",
        )
        results = repo.search_fts("ClaimRef", repo="k8s")
        assert any(r.name == "do_thing" for r in results)

    def test_match_via_file_path(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        repo.add(
            _sym("anything", file="/pkg/kubelet/cm/dra/manager.go"),
            "k8s",
        )
        results = repo.search_fts("manager", repo="k8s")
        assert any(r.name == "anything" for r in results)

    def test_limit_honored(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        for i in range(20):
            repo.add(_sym(f"handler_{i}", signature="def handler"), "k8s")
        results = repo.search_fts("handler", repo="k8s", limit=5)
        assert len(results) == 5

    def test_repo_scope_filters(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        repo.add(_sym("shared_name"), "repo_a")
        repo.add(_sym("shared_name"), "repo_b")
        a = repo.search_fts("shared_name", repo="repo_a")
        b = repo.search_fts("shared_name", repo="repo_b")
        assert len(a) == 1
        assert len(b) == 1
        # Without a repo scope we should see both rows.
        unscoped = repo.search_fts("shared_name")
        assert len(unscoped) == 2

    def test_ranking_prefers_better_match(self, db: Database) -> None:
        """BM25 should rank a symbol whose name matches above one that only
        coincidentally matches via the file path."""
        repo = SymbolRepository(db.connection)
        repo.add(
            _sym("misc_helper", file="/pkg/foo/bar.go"),
            "k8s",
        )
        repo.add(
            _sym("unprepareResources", file="/pkg/foo/bar.go"),
            "k8s",
        )
        results = repo.search_fts("unprepareResources", repo="k8s")
        assert results, "expected at least one match"
        assert results[0].name == "unprepareResources"

    def test_returns_symbol_dataclass_with_id(self, db: Database) -> None:
        repo = SymbolRepository(db.connection)
        sid = repo.add(_sym("MyClass", kind="class"), "k8s")
        results = repo.search_fts("MyClass", repo="k8s")
        assert len(results) == 1
        assert isinstance(results[0], Symbol)
        assert results[0].id == sid
        assert results[0].kind == "class"
