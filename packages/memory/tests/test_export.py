"""Tests for memory.export — observation and decision markdown formatters."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contracts.models import Decision, Observation
from memory.export import (
    _slugify,
    export_decisions_adr,
    export_observations,
    format_decision_md,
    format_observation_md,
)


def _obs(**kwargs) -> Observation:
    defaults = {
        "summary": "fixed auth bug",
        "task_type": "debug",
        "files_touched": ["auth.py", "tests/test_auth.py"],
        "commands_run": ["pytest tests/test_auth.py"],
        "fix_summary": "added null-check on token",
        "commit_sha": "abc1234",
        "timestamp": datetime.now(UTC) - timedelta(days=5),
    }
    defaults.update(kwargs)
    return Observation(**defaults)


def _dec(**kwargs) -> Decision:
    defaults = {
        "title": "Use SQLite for local storage",
        "status": "accepted",
        "context": "Need offline-capable storage with FTS support.",
        "decision": "SQLite + FTS5 chosen over PostgreSQL for simplicity.",
        "consequences": "Scales to ~10k observations without issues.",
        "tags": ["storage", "sqlite"],
    }
    defaults.update(kwargs)
    return Decision(**defaults)


class TestSlugify:
    def test_lowercases(self):
        assert _slugify("Use SQLite") == "use-sqlite"

    def test_replaces_spaces(self):
        assert _slugify("Use SQLite for storage") == "use-sqlite-for-storage"

    def test_strips_special_chars(self):
        assert _slugify("Use SQLite (v3.40)") == "use-sqlite-v340"

    def test_empty_string(self):
        assert _slugify("") == ""


class TestFormatObservationMd:
    def test_includes_summary(self):
        obs = _obs()
        md = format_observation_md(obs)
        assert "fixed auth bug" in md

    def test_includes_task_type(self):
        obs = _obs()
        md = format_observation_md(obs)
        assert "debug" in md

    def test_includes_files_when_not_redacted(self):
        obs = _obs()
        md = format_observation_md(obs, redact=False)
        assert "auth.py" in md

    def test_excludes_files_when_redacted(self):
        obs = _obs()
        md = format_observation_md(obs, redact=True)
        assert "auth.py" not in md

    def test_excludes_commit_sha_when_redacted(self):
        obs = _obs()
        md = format_observation_md(obs, redact=True)
        assert "abc1234" not in md

    def test_keeps_fix_summary_when_redacted(self):
        obs = _obs()
        md = format_observation_md(obs, redact=True)
        assert "added null-check on token" in md

    def test_includes_confidence_and_age(self):
        obs = _obs()
        md = format_observation_md(obs)
        assert "Confidence" in md
        assert "Age" in md


class TestFormatDecisionMd:
    def test_includes_title(self):
        dec = _dec()
        md = format_decision_md(dec)
        assert "Use SQLite for local storage" in md

    def test_includes_status(self):
        dec = _dec()
        md = format_decision_md(dec)
        assert "accepted" in md

    def test_includes_context_section(self):
        dec = _dec()
        md = format_decision_md(dec)
        assert "## Context" in md
        assert "offline-capable" in md

    def test_includes_decision_section(self):
        dec = _dec()
        md = format_decision_md(dec)
        assert "## Decision" in md
        assert "FTS5" in md

    def test_includes_tags(self):
        dec = _dec()
        md = format_decision_md(dec)
        assert "sqlite" in md

    def test_superseded_shows_link(self):
        dec = _dec(superseded_by="new-uuid-1234")
        md = format_decision_md(dec)
        assert "Superseded by" in md
        assert "new-uuid-1234" in md


class TestExportObservations:
    def test_creates_file(self, tmp_path: Path):
        obs = [_obs()]
        out = tmp_path / "memory.md"
        count = export_observations(obs, out)
        assert count == 1
        assert out.exists()

    def test_creates_parent_dirs(self, tmp_path: Path):
        obs = [_obs()]
        out = tmp_path / "subdir" / "nested" / "memory.md"
        export_observations(obs, out)
        assert out.exists()

    def test_content_includes_summary(self, tmp_path: Path):
        obs = [_obs()]
        out = tmp_path / "memory.md"
        export_observations(obs, out)
        content = out.read_text()
        assert "fixed auth bug" in content

    def test_redacted_excludes_files(self, tmp_path: Path):
        obs = [_obs()]
        out = tmp_path / "memory.md"
        export_observations(obs, out, redact=True)
        content = out.read_text()
        assert "auth.py" not in content

    def test_returns_count(self, tmp_path: Path):
        obs = [_obs(), _obs(summary="second obs")]
        out = tmp_path / "memory.md"
        count = export_observations(obs, out)
        assert count == 2

    def test_empty_list_writes_header(self, tmp_path: Path):
        out = tmp_path / "memory.md"
        count = export_observations([], out)
        assert count == 0
        assert out.exists()


class TestExportDecisionsAdr:
    def test_creates_files(self, tmp_path: Path):
        decs = [_dec()]
        count = export_decisions_adr(decs, tmp_path)
        assert count == 1
        files = list(tmp_path.glob("*.md"))
        assert len(files) == 1

    def test_filename_format(self, tmp_path: Path):
        decs = [_dec()]
        export_decisions_adr(decs, tmp_path)
        files = list(tmp_path.glob("*.md"))
        assert files[0].name.startswith("0001-")
        assert "sqlite" in files[0].name

    def test_filters_by_status(self, tmp_path: Path):
        decs = [
            _dec(status="accepted"),
            _dec(title="Other decision", status="deprecated"),
        ]
        count = export_decisions_adr(decs, tmp_path, statuses=["accepted"])
        assert count == 1

    def test_all_statuses_when_none(self, tmp_path: Path):
        decs = [
            _dec(status="accepted"),
            _dec(title="Other decision", status="deprecated"),
        ]
        count = export_decisions_adr(decs, tmp_path, statuses=["accepted", "deprecated"])
        assert count == 2

    def test_creates_parent_dirs(self, tmp_path: Path):
        decs = [_dec()]
        out_dir = tmp_path / "docs" / "adr"
        export_decisions_adr(decs, out_dir)
        assert out_dir.exists()
        assert len(list(out_dir.glob("*.md"))) == 1

    def test_content_matches_decision(self, tmp_path: Path):
        decs = [_dec()]
        export_decisions_adr(decs, tmp_path)
        content = (tmp_path / "0001-use-sqlite-for-local-storage.md").read_text()
        assert "Use SQLite for local storage" in content
        assert "FTS5" in content
