"""Tests for `memory show` and `memory migrate-from-sqlite` CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_FRONTMATTER = dedent("""\
    ---
    id: {id}
    type: observation
    task: debug
    files_touched:
      - packages/core/src/core/orchestrator.py
    created_at: 2026-04-24T13:58:00+00:00
    author: context-router
    ---

    This is the body text of the observation.
""")


def _write_obs_file(observations_dir: Path, stem: str, body: str = "") -> Path:
    """Write a minimal .md observation file and return its path."""
    observations_dir.mkdir(parents=True, exist_ok=True)
    content = _VALID_FRONTMATTER.format(id=stem)
    if body:
        content = content.rstrip("\n") + "\n\n" + body + "\n"
    dest = observations_dir / f"{stem}.md"
    dest.write_text(content, encoding="utf-8")
    return dest


def _make_db(tmp_path: Path):
    """Create and initialise a SQLite DB with ObservationStore; return (store, db)."""
    from memory.store import ObservationStore
    from storage_sqlite.database import Database

    db_path = tmp_path / ".context-router" / "context-router.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)
    db.initialize()
    store = ObservationStore(db)
    return store, db


# ---------------------------------------------------------------------------
# memory show
# ---------------------------------------------------------------------------


class TestMemoryShow:
    def test_show_finds_file(self, tmp_path: Path):
        """Exact id match returns file contents and exits 0."""
        obs_dir = tmp_path / ".context-router" / "memory" / "observations"
        stem = "2026-04-24-fixed-checkout-dedup"
        _write_obs_file(obs_dir, stem)

        result = runner.invoke(
            app, ["memory", "show", stem, "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert "id: " + stem in result.output
        assert "task: debug" in result.output

    def test_show_not_found(self, tmp_path: Path):
        """Non-existent id exits 1 and writes error to stderr."""
        obs_dir = tmp_path / ".context-router" / "memory" / "observations"
        obs_dir.mkdir(parents=True, exist_ok=True)

        result = runner.invoke(
            app,
            ["memory", "show", "nonexistent-id", "--project-root", str(tmp_path)],
        )
        assert result.exit_code == 1
        assert "No observation found" in result.output

    def test_show_partial_match(self, tmp_path: Path):
        """Prefix match succeeds when exact id not found."""
        obs_dir = tmp_path / ".context-router" / "memory" / "observations"
        _write_obs_file(obs_dir, "2026-04-24-checkout")

        result = runner.invoke(
            app, ["memory", "show", "2026-04-24", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert "2026-04-24-checkout" in result.output

    def test_show_json_output(self, tmp_path: Path):
        """--json flag returns valid JSON with id and body keys."""
        obs_dir = tmp_path / ".context-router" / "memory" / "observations"
        stem = "2026-04-24-fixed-checkout-dedup"
        _write_obs_file(obs_dir, stem, body="Extra body content.")

        result = runner.invoke(
            app,
            ["memory", "show", stem, "--project-root", str(tmp_path), "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["id"] == stem
        assert "body" in data
        assert isinstance(data["body"], str)


# ---------------------------------------------------------------------------
# memory migrate-from-sqlite
# ---------------------------------------------------------------------------


class TestMemoryMigrateFromSqlite:
    def test_migrate_writes_files(self, tmp_path: Path):
        """Two valid observations produce two .md files."""
        from contracts.models import Observation

        store, db = _make_db(tmp_path)
        try:
            obs1 = Observation(
                summary="Fixed a long-standing checkout deduplication bug in the orchestrator pipeline",
                task_type="debug",
                files_touched=["packages/core/src/core/orchestrator.py"],
            )
            obs2 = Observation(
                summary="Implemented token-efficient context selection for the handover mode feature",
                task_type="implement",
                files_touched=["packages/core/src/core/ranker.py"],
            )
            store.add(obs1)
            store.add(obs2)
        finally:
            db.close()

        result = runner.invoke(
            app,
            ["memory", "migrate-from-sqlite", "--project-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        obs_dir = tmp_path / ".context-router" / "memory" / "observations"
        md_files = list(obs_dir.glob("*.md"))
        assert len(md_files) == 2
        assert "Migrated 2 / 2" in result.output

    def test_migrate_skips_rejected(self, tmp_path: Path):
        """Observations with summary < 60 chars are skipped by the write gate."""
        from contracts.models import Observation

        store, db = _make_db(tmp_path)
        try:
            short_obs = Observation(
                summary="too short",
                task_type="debug",
                files_touched=["packages/core/src/core/orchestrator.py"],
            )
            store.add(short_obs)
        finally:
            db.close()

        result = runner.invoke(
            app,
            ["memory", "migrate-from-sqlite", "--project-root", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        obs_dir = tmp_path / ".context-router" / "memory" / "observations"
        md_files = list(obs_dir.glob("*.md")) if obs_dir.exists() else []
        assert len(md_files) == 0
        assert "1 skipped" in result.output

    def test_migrate_dry_run(self, tmp_path: Path):
        """--dry-run reports what would be written but creates no files."""
        from contracts.models import Observation

        store, db = _make_db(tmp_path)
        try:
            obs = Observation(
                summary="Fixed a long-standing checkout deduplication bug in the orchestrator pipeline",
                task_type="debug",
                files_touched=["packages/core/src/core/orchestrator.py"],
            )
            store.add(obs)
        finally:
            db.close()

        result = runner.invoke(
            app,
            [
                "memory",
                "migrate-from-sqlite",
                "--project-root",
                str(tmp_path),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        obs_dir = tmp_path / ".context-router" / "memory" / "observations"
        md_files = list(obs_dir.glob("*.md")) if obs_dir.exists() else []
        assert len(md_files) == 0
        assert "dry-run" in result.output.lower()

    def test_migrate_no_db(self, tmp_path: Path):
        """Missing database exits 1 with an error message."""
        result = runner.invoke(
            app,
            ["memory", "migrate-from-sqlite", "--project-root", str(tmp_path)],
        )
        assert result.exit_code == 1

    def test_migrate_json_output(self, tmp_path: Path):
        """--json flag produces a JSON object with migrated/skipped/total keys."""
        from contracts.models import Observation

        store, db = _make_db(tmp_path)
        try:
            obs = Observation(
                summary="Fixed a long-standing checkout deduplication bug in the orchestrator pipeline",
                task_type="debug",
                files_touched=["packages/core/src/core/orchestrator.py"],
            )
            store.add(obs)
        finally:
            db.close()

        result = runner.invoke(
            app,
            [
                "memory",
                "migrate-from-sqlite",
                "--project-root",
                str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "migrated" in data
        assert "skipped" in data
        assert "total" in data
        assert data["total"] == 1
        assert data["migrated"] == 1
