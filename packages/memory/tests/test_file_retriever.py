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


# ---------------------------------------------------------------------------
# v4.3 Phase A — Staleness detection
# ---------------------------------------------------------------------------

def _git(*args: str, cwd: Path) -> None:
    import subprocess
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "t@t.t", cwd=root)
    _git("config", "user.name", "T", cwd=root)
    _git("config", "commit.gpgsign", "false", cwd=root)


class TestStalenessFields:
    """MemoryHit carries stale / staleness_reason / source_repo with safe defaults."""

    def test_memhit_defaults(self) -> None:
        h = MemoryHit(
            id="x", path=Path("/tmp/x.md"), excerpt="e", score=1.0
        )
        assert h.stale is False
        assert h.staleness_reason is None
        assert h.source_repo == "local"


class TestStalenessChecker:
    """ObservationStalenessChecker detects missing_file and dormant."""

    def test_missing_file_detected(self, tmp_path: Path) -> None:
        from memory.staleness import ObservationStalenessChecker
        _init_repo(tmp_path)
        (tmp_path / "present.py").write_text("x")
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-q", "-m", "init", cwd=tmp_path)

        checker = ObservationStalenessChecker()
        is_stale, reason = checker.check(["missing_file.py"], tmp_path)
        assert is_stale is True
        assert "missing_file" in reason

    def test_present_file_not_stale(self, tmp_path: Path) -> None:
        from memory.staleness import ObservationStalenessChecker
        _init_repo(tmp_path)
        (tmp_path / "existing.py").write_text("x")
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-q", "-m", "init", cwd=tmp_path)

        checker = ObservationStalenessChecker()
        is_stale, reason = checker.check(["existing.py"], tmp_path)
        assert is_stale is False

    def test_empty_files_not_stale(self, tmp_path: Path) -> None:
        from memory.staleness import ObservationStalenessChecker
        checker = ObservationStalenessChecker()
        is_stale, reason = checker.check([], tmp_path)
        assert is_stale is False
        assert reason == ""

    def test_dormant_check_informational(self, tmp_path: Path) -> None:
        from memory.staleness import ObservationStalenessChecker
        from datetime import datetime, timezone, timedelta
        _init_repo(tmp_path)
        (tmp_path / "ok.py").write_text("x")
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-q", "-m", "init", cwd=tmp_path)

        old_date = datetime.now(tz=timezone.utc) - timedelta(days=100)
        checker = ObservationStalenessChecker()
        is_stale, reason = checker.check(["ok.py"], tmp_path, created_at=old_date)
        # dormant is informational: file is present, so is_stale=False
        assert is_stale is False
        assert "dormant" in reason


class TestStalenessWiredIntoRetriever:
    """retrieve_observations sets hit.stale=True when a referenced file is deleted."""

    def test_stale_hit_flagged(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "to_delete.py").write_text("x")
        md_dir = _memory_dir(tmp_path)
        obs_dir = md_dir / "observations"
        _write_obs(obs_dir, "2026-01-01-stale", "Stale obs",
                   files_touched=["src/to_delete.py"])
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-q", "-m", "init", cwd=tmp_path)

        # Delete the file and commit
        (tmp_path / "src" / "to_delete.py").unlink()
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-q", "-m", "remove", cwd=tmp_path)

        hits = retrieve_observations("stale", md_dir, k=5, project_root=tmp_path)
        assert len(hits) >= 1
        stale_hits = [h for h in hits if h.stale]
        assert len(stale_hits) >= 1
        assert stale_hits[0].staleness_reason is not None
        assert "missing_file" in stale_hits[0].staleness_reason

    def test_non_stale_hit_not_flagged(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "present.py").write_text("x")
        md_dir = _memory_dir(tmp_path)
        obs_dir = md_dir / "observations"
        _write_obs(obs_dir, "2026-01-01-fresh", "Fresh obs",
                   files_touched=["src/present.py"])
        _git("add", "-A", cwd=tmp_path)
        _git("commit", "-q", "-m", "init", cwd=tmp_path)

        hits = retrieve_observations("fresh", md_dir, k=5, project_root=tmp_path)
        assert all(not h.stale for h in hits)


# ---------------------------------------------------------------------------
# v4.3 Phase B — Memory federation
# ---------------------------------------------------------------------------

class TestFederation:
    """retrieve_observations with federated_roots returns cross-repo hits."""

    def test_federated_committed_obs_included(self, tmp_path: Path) -> None:
        local_root = tmp_path / "local"
        sibling_root = tmp_path / "sibling"
        _init_repo(local_root)
        _init_repo(sibling_root)

        # Local observation
        local_md = _memory_dir(local_root)
        local_obs = local_md / "observations"
        _write_obs(local_obs, "2026-04-01-local", "Local checkout fix",
                   files_touched=["src/local.py"])
        _git("add", "-A", cwd=local_root)
        _git("commit", "-q", "-m", "init", cwd=local_root)

        # Sibling observation (committed)
        sib_md = _memory_dir(sibling_root)
        sib_obs = sib_md / "observations"
        _write_obs(sib_obs, "2026-04-01-sib", "Sibling checkout fix",
                   files_touched=["src/sib.py"])
        _git("add", "-A", cwd=sibling_root)
        _git("commit", "-q", "-m", "init", cwd=sibling_root)

        hits = retrieve_observations(
            "checkout",
            local_md,
            k=10,
            project_root=local_root,
            federated_roots=[("sibling", sibling_root)],
        )
        source_repos = {h.source_repo for h in hits}
        assert "local" in source_repos
        assert "sibling" in source_repos

    def test_federated_staged_obs_excluded(self, tmp_path: Path) -> None:
        local_root = tmp_path / "local"
        sibling_root = tmp_path / "sibling"
        _init_repo(local_root)
        _init_repo(sibling_root)

        local_md = _memory_dir(local_root)
        local_obs = local_md / "observations"
        _write_obs(local_obs, "2026-04-01-local", "Local auth fix",
                   files_touched=["src/local.py"])
        _git("add", "-A", cwd=local_root)
        _git("commit", "-q", "-m", "init", cwd=local_root)

        # Sibling has a staged (uncommitted) observation
        sib_md = _memory_dir(sibling_root)
        sib_obs = sib_md / "observations"
        # Make an initial commit so the repo is valid, but do NOT commit the obs
        (sibling_root / "README.md").write_text("hi")
        _git("add", "README.md", cwd=sibling_root)
        _git("commit", "-q", "-m", "init", cwd=sibling_root)
        _write_obs(sib_obs, "2026-04-01-staged", "Staged-only obs",
                   files_touched=["src/sib.py"])
        # Stage the obs file but do not commit
        _git("add", "-A", cwd=sibling_root)

        hits = retrieve_observations(
            "auth",
            local_md,
            k=10,
            project_root=local_root,
            federated_roots=[("sibling", sibling_root)],
        )
        sibling_hits = [h for h in hits if h.source_repo == "sibling"]
        assert sibling_hits == [], f"Staged-only obs must not federate: {sibling_hits}"

    def test_missing_sibling_warns_and_continues(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        local_root = tmp_path / "local"
        _init_repo(local_root)
        local_md = _memory_dir(local_root)
        local_obs = local_md / "observations"
        _write_obs(local_obs, "2026-04-01-local", "Local impl fix")
        _git("add", "-A", cwd=local_root)
        _git("commit", "-q", "-m", "init", cwd=local_root)

        hits = retrieve_observations(
            "impl",
            local_md,
            k=10,
            project_root=local_root,
            federated_roots=[("missing-repo", tmp_path / "does_not_exist")],
        )
        # Local hits still returned
        assert len(hits) >= 1
        assert all(h.source_repo == "local" for h in hits)
        captured = capsys.readouterr()
        assert "missing-repo" in captured.err
