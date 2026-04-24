"""Tests for memory.file_retriever — BM25+recency observation retrieval."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from memory.file_retriever import MemoryHit, _classify_memory_files, retrieve_observations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_obs(
    obs_dir: Path,
    stem: str,
    summary: str,
    files_touched: list[str] | None = None,
    task: str = "debug",
    created_at: str = "2026-04-24T12:00:00+00:00",
) -> Path:
    """Write a minimal YAML-frontmatter .md file directly (no MemoryFileWriter)."""
    obs_dir.mkdir(parents=True, exist_ok=True)
    ft_lines = "\n".join(f"  - {f}" for f in (files_touched or ["packages/foo/bar.py"]))
    content = (
        f"---\n"
        f"id: {stem}\n"
        f"type: observation\n"
        f"task: {task}\n"
        f"files_touched:\n{ft_lines}\n"
        f"created_at: {created_at}\n"
        f"author: context-router\n"
        f"---\n"
        f"\n"
        f"{summary}\n"
    )
    path = obs_dir / f"{stem}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _memory_dir(tmp_path: Path) -> Path:
    """Return the memory_dir path (does NOT create it — tests decide themselves)."""
    return tmp_path / ".context-router" / "memory"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRetrieveEmptyDir:
    """retrieve_observations returns [] when there are no .md files."""

    def test_no_observations_dir(self, tmp_path: Path) -> None:
        """memory_dir/observations/ does not exist → empty list."""
        md = _memory_dir(tmp_path)
        # Don't create the directory at all.
        result = retrieve_observations("checkout", md, k=8)
        assert result == []

    def test_empty_observations_dir(self, tmp_path: Path) -> None:
        """Observations dir exists but contains no .md files → empty list."""
        md = _memory_dir(tmp_path)
        (md / "observations").mkdir(parents=True)
        result = retrieve_observations("checkout", md, k=8)
        assert result == []


class TestRetrieveTopK:
    """With k=3 and 10 docs, at most 3 results are returned."""

    def test_returns_at_most_k(self, tmp_path: Path) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"
        for i in range(10):
            _write_obs(
                obs_dir,
                stem=f"2026-04-24-obs-{i:02d}",
                summary=f"Fixed bug number {i} in the auth module to prevent token overflow",
            )
        result = retrieve_observations("auth token overflow", md, k=3)
        assert len(result) <= 3

    def test_all_results_are_memory_hits(self, tmp_path: Path) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"
        for i in range(5):
            _write_obs(
                obs_dir,
                stem=f"2026-04-24-obs-{i:02d}",
                summary=f"Implemented feature {i} for the payment pipeline integration",
            )
        result = retrieve_observations("payment pipeline", md, k=5)
        assert all(isinstance(h, MemoryHit) for h in result)


class TestBM25Relevance:
    """The most relevant document appears first."""

    def test_relevant_doc_ranked_first(self, tmp_path: Path) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"

        # Relevant: body contains the query terms
        _write_obs(
            obs_dir,
            stem="2026-04-24-relevant",
            summary="Fixed checkout dedup in pack table by normalising path separators for all entries",
            created_at="2026-04-24T12:00:00+00:00",
        )
        # Irrelevant: body is about something entirely different
        _write_obs(
            obs_dir,
            stem="2026-04-24-irrelevant",
            summary="Updated the database migration scripts for the new schema version upgrade",
            created_at="2026-04-24T12:00:00+00:00",
        )

        result = retrieve_observations("checkout dedup", md, k=8)
        assert len(result) >= 1
        assert result[0].id == "2026-04-24-relevant"

    def test_hit_has_expected_fields(self, tmp_path: Path) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"
        _write_obs(
            obs_dir,
            stem="2026-04-24-my-obs",
            summary="Fixed checkout dedup in pack table by normalising path separators",
            files_touched=["packages/core/orchestrator.py"],
            task="debug",
        )
        result = retrieve_observations("checkout dedup", md, k=1)
        assert len(result) == 1
        hit = result[0]
        assert hit.id == "2026-04-24-my-obs"
        assert "checkout" in hit.excerpt.lower() or "dedup" in hit.excerpt.lower()
        assert isinstance(hit.score, float)
        assert hit.score > 0
        assert "packages/core/orchestrator.py" in hit.files_touched
        assert hit.task == "debug"


class TestRecencyBoost:
    """A newer document should score higher than an older identical one."""

    def test_newer_scores_higher(self, tmp_path: Path) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"

        # Both have the same summary text (same BM25 score), but different ages.
        shared_summary = (
            "Fixed the authentication token refresh logic for all user sessions properly"
        )
        _write_obs(
            obs_dir,
            stem="2020-01-01-old-obs",
            summary=shared_summary,
            created_at="2020-01-01T00:00:00+00:00",
        )
        _write_obs(
            obs_dir,
            stem="2026-04-24-new-obs",
            summary=shared_summary,
            created_at="2026-04-24T12:00:00+00:00",
        )

        result = retrieve_observations("authentication token refresh", md, k=8)
        assert len(result) == 2
        # The newer observation must outrank the older one.
        ids_in_order = [h.id for h in result]
        assert ids_in_order.index("2026-04-24-new-obs") < ids_in_order.index("2020-01-01-old-obs"), (
            f"Expected newer first, got: {ids_in_order}"
        )


class TestNoMatchReturnsByRecency:
    """When no BM25 matches exist, documents are sorted by recency."""

    def test_fallback_to_recency_order(self, tmp_path: Path) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"

        _write_obs(
            obs_dir,
            stem="2024-01-01-older",
            summary="Some unrelated content about database sharding techniques and performance",
            created_at="2024-01-01T00:00:00+00:00",
        )
        _write_obs(
            obs_dir,
            stem="2026-04-24-newer",
            summary="Some unrelated content about database sharding techniques and performance",
            created_at="2026-04-24T12:00:00+00:00",
        )

        # This query should not match either document via BM25.
        result = retrieve_observations("xyzzynosuchterm", md, k=8)
        assert len(result) == 2
        # Newer should be first (recency-only sort).
        assert result[0].id == "2026-04-24-newer"
        assert result[1].id == "2024-01-01-older"


class TestKCeiling:
    """With 5 docs and k=3, exactly 3 results are returned."""

    def test_returns_exactly_k_when_pool_exceeds_k(self, tmp_path: Path) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"
        for i in range(5):
            _write_obs(
                obs_dir,
                stem=f"2026-04-24-doc-{i:02d}",
                summary=f"Implemented checkout dedup fix number {i} for the core pack pipeline",
            )
        result = retrieve_observations("checkout dedup pack", md, k=3)
        assert len(result) == 3

    def test_returns_all_when_pool_smaller_than_k(self, tmp_path: Path) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"
        for i in range(2):
            _write_obs(
                obs_dir,
                stem=f"2026-04-24-doc-{i:02d}",
                summary=f"Fixed auth bug number {i} in the session management service",
            )
        result = retrieve_observations("auth session", md, k=10)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# T2 — Observation provenance tests
# ---------------------------------------------------------------------------


class TestProvenanceDefaults:
    """Without project_root all hits default to provenance='committed'."""

    def test_retrieve_observations_provenance_defaults_committed(
        self, tmp_path: Path
    ) -> None:
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"
        _write_obs(obs_dir, stem="2026-04-24-obs-a", summary="Fixed auth token refresh for all users")
        _write_obs(obs_dir, stem="2026-04-24-obs-b", summary="Improved checkout dedup pipeline logic")

        result = retrieve_observations("auth checkout", md, k=8)
        assert len(result) >= 1
        assert all(h.provenance == "committed" for h in result), (
            f"Expected all provenance='committed', got: {[h.provenance for h in result]}"
        )


class TestClassifyMemoryFilesGraceful:
    """_classify_memory_files returns {} gracefully when git is unavailable."""

    def test_classify_memory_files_graceful_on_no_git(
        self, tmp_path: Path
    ) -> None:
        # tmp_path is not a git repo — function must return {} without raising
        obs_dir = tmp_path / "observations"
        obs_dir.mkdir(parents=True)
        (obs_dir / "2026-04-24-test.md").write_text("# test\n", encoding="utf-8")

        result = _classify_memory_files(obs_dir, tmp_path)
        assert result == {}, f"Expected empty dict, got: {result}"


class TestProvenanceWithNonGitRoot:
    """retrieve_observations with a non-git project_root falls back gracefully."""

    def test_retrieve_observations_with_project_root_non_git(
        self, tmp_path: Path
    ) -> None:
        # Use tmp_path as both the project root (not a git repo) and memory root
        md = _memory_dir(tmp_path)
        obs_dir = md / "observations"
        _write_obs(obs_dir, stem="2026-04-24-obs-fallback", summary="Checkout dedup fix applied")

        # non-git project_root → _classify_memory_files returns {} →
        # all hits default to provenance="committed" and none are filtered
        result = retrieve_observations(
            "checkout dedup", md, k=8, project_root=tmp_path
        )
        assert len(result) >= 1
        assert all(h.provenance == "committed" for h in result), (
            f"Expected fallback to committed, got: {[h.provenance for h in result]}"
        )
