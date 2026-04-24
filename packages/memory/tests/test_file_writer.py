"""Tests for memory.file_writer — MemoryFileWriter and WriteResult."""

from __future__ import annotations

import yaml
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.models import Observation
from memory.file_writer import MemoryFileWriter, WriteResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _long_summary(text: str = "Fixed checkout dedup in pack table by normalising path separators") -> str:
    """Return a summary that is guaranteed to pass the 60-char gate."""
    assert len(text.strip()) >= 60, "adjust default text"
    return text


def _make_obs(
    summary: str | None = None,
    task_type: str = "debug",
    files_touched: list[str] | None = None,
    fix_summary: str = "",
    timestamp: datetime | None = None,
) -> Observation:
    return Observation(
        summary=summary if summary is not None else _long_summary(),
        task_type=task_type,
        files_touched=files_touched if files_touched is not None else ["packages/core/src/core/orchestrator.py"],
        fix_summary=fix_summary,
        timestamp=timestamp or datetime(2026, 4, 24, 13, 58, 0, tzinfo=timezone.utc),
    )


def _parse_frontmatter(path: Path) -> dict:
    """Split on '---\\n' delimiters and parse the YAML middle block."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---\n", 2)
    assert len(parts) == 3, f"Expected three parts in frontmatter split, got {len(parts)}"
    return yaml.safe_load(parts[1])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWriteCreatesFile:
    def test_write_creates_file(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs()

        result = writer.write_observation(obs)

        assert result.written is True
        assert result.path is not None
        assert result.path.exists()
        assert result.path.suffix == ".md"
        assert result.path.parent == memory_dir / "observations"


class TestWriteGateShortSummary:
    def test_write_gate_short_summary(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(summary="too short")

        result = writer.write_observation(obs)

        assert result.written is False
        assert result.path is None
        assert "summary" in result.reason.lower()

    def test_exactly_59_chars_rejected(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(summary="x" * 59)

        result = writer.write_observation(obs)

        assert result.written is False
        assert "summary" in result.reason.lower()

    def test_exactly_60_chars_accepted(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(summary="x" * 60)

        result = writer.write_observation(obs)

        assert result.written is True


class TestWriteGateNoFiles:
    def test_write_gate_no_files(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(files_touched=[])

        result = writer.write_observation(obs)

        assert result.written is False
        assert result.path is None
        assert "files" in result.reason.lower()


class TestWriteGateScratchType:
    def test_write_gate_scratch_type(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(task_type="scratch")

        result = writer.write_observation(obs)

        assert result.written is False
        assert result.path is None

    def test_non_scratch_type_accepted(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(task_type="debug")

        result = writer.write_observation(obs)

        assert result.written is True


class TestWriteIdempotent:
    def test_write_idempotent(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs()

        result1 = writer.write_observation(obs)
        result2 = writer.write_observation(obs)

        assert result1.written is True
        assert result2.written is True
        assert result1.path == result2.path

        # Confirm only one file exists
        obs_dir = memory_dir / "observations"
        md_files = list(obs_dir.glob("*.md"))
        assert len(md_files) == 1


class TestUpdateIndexGeneratesMemoryMd:
    def test_update_index_generates_memory_md(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)

        obs1 = _make_obs(
            summary="Fixed checkout dedup in pack table by normalising path separators",
            timestamp=datetime(2026, 4, 24, 10, 0, 0, tzinfo=timezone.utc),
        )
        obs2 = _make_obs(
            summary="Implemented BM25 retriever for memory search across stored observations",
            timestamp=datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc),
        )

        writer.write_observation(obs1)
        writer.write_observation(obs2)
        writer.update_index()

        index_path = memory_dir / "MEMORY.md"
        assert index_path.exists()

        content = index_path.read_text(encoding="utf-8")
        assert "# Memory Index" in content

        # Both stems must appear as link anchors
        stem1 = writer.write_observation(obs1).path.stem  # type: ignore[union-attr]
        stem2 = writer.write_observation(obs2).path.stem  # type: ignore[union-attr]
        assert stem1 in content
        assert stem2 in content

    def test_update_index_sorted_newest_first(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)

        obs_old = _make_obs(
            summary="Fixed checkout dedup in pack table by normalising path separators",
            timestamp=datetime(2026, 4, 20, 10, 0, 0, tzinfo=timezone.utc),
        )
        obs_new = _make_obs(
            summary="Implemented BM25 retriever for memory search across stored observations",
            timestamp=datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc),
        )

        writer.write_observation(obs_old)
        writer.write_observation(obs_new)
        writer.update_index()

        content = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
        lines = [ln for ln in content.splitlines() if ln.startswith("- [")]
        # Newer entry (2026-04-25) should appear before older (2026-04-20)
        assert lines[0].startswith("- [2026-04-25")
        assert lines[1].startswith("- [2026-04-20")


class TestFileFrontmatter:
    def test_file_format_frontmatter(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        ts = datetime(2026, 4, 24, 13, 58, 0, tzinfo=timezone.utc)
        obs = _make_obs(
            summary="Fixed checkout dedup in pack table by normalising path separators",
            task_type="debug",
            files_touched=["packages/core/src/core/orchestrator.py"],
            timestamp=ts,
        )

        result = writer.write_observation(obs)
        assert result.written is True
        assert result.path is not None

        fm = _parse_frontmatter(result.path)

        assert fm["id"] is not None
        assert fm["type"] == "observation"
        assert fm["task"] == "debug"
        assert "packages/core/src/core/orchestrator.py" in fm["files_touched"]
        assert fm["created_at"] is not None
        assert fm["author"] == "context-router"

    def test_frontmatter_id_matches_filename_stem(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs()

        result = writer.write_observation(obs)
        assert result.written is True
        assert result.path is not None

        fm = _parse_frontmatter(result.path)
        assert fm["id"] == result.path.stem

    def test_frontmatter_task_defaults_to_general_when_empty(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(task_type="")

        result = writer.write_observation(obs)
        assert result.written is True
        assert result.path is not None

        fm = _parse_frontmatter(result.path)
        assert fm["task"] == "general"

    def test_fix_summary_appears_in_body(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(fix_summary="Added normalisation step before comparison.")

        result = writer.write_observation(obs)
        assert result.written is True
        assert result.path is not None

        text = result.path.read_text(encoding="utf-8")
        assert "Added normalisation step before comparison." in text

    def test_empty_fix_summary_not_in_body(self, tmp_path: Path) -> None:
        memory_dir = tmp_path / "memory"
        writer = MemoryFileWriter(memory_dir)
        obs = _make_obs(fix_summary="")

        result = writer.write_observation(obs)
        assert result.written is True
        assert result.path is not None

        # Split on frontmatter; body should only contain the summary paragraph
        text = result.path.read_text(encoding="utf-8")
        parts = text.split("---\n", 2)
        body = parts[2].strip()
        assert body == obs.summary
