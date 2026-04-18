"""Tests for the cross-community coupling warning.

Phase-4 outcome ``cross-community-coupling``: when a multi-repo workspace
pack contains at least ``capabilities.coupling_warn_threshold`` edges whose
endpoints live in different communities, a warning is written to stderr.
Single-repo invocations never emit this warning.
"""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest
from contracts.config import CapabilitiesConfig, ContextRouterConfig
from contracts.models import RepoDescriptor, WorkspaceDescriptor
from workspace import WorkspaceLoader

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _init_repo(path: Path) -> None:
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(path)],
        check=True,
        capture_output=True,
    )


def _seed_cross_community_edges(
    db_path: Path,
    repo_name: str,
    n_edges: int,
    *,
    same_community: bool = False,
) -> None:
    """Insert ``2*n_edges`` symbols and ``n_edges`` edges.

    If ``same_community`` is True, every symbol is placed in community 1 so
    no edge crosses a community boundary. Otherwise even-indexed symbols go
    to community 1 and odd-indexed to community 2, making every edge a
    cross-community ``calls`` edge.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        ids: list[int] = []
        for i in range(2 * n_edges):
            community = 1 if same_community else (1 if i % 2 == 0 else 2)
            cur.execute(
                "INSERT INTO symbols(repo, file_path, name, kind, community_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (repo_name, f"src/mod_{i}.py", f"sym_{i}", "function", community),
            )
            ids.append(int(cur.lastrowid or 0))
        for i in range(n_edges):
            cur.execute(
                "INSERT INTO edges(repo, from_symbol_id, to_symbol_id, edge_type) "
                "VALUES (?, ?, ?, 'calls')",
                (repo_name, ids[2 * i], ids[2 * i + 1]),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def two_repo_ws(tmp_path: Path):
    """Two initialised repos wired into a workspace.yaml."""
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    _init_repo(repo_a)
    _init_repo(repo_b)

    ws = WorkspaceDescriptor(
        name="xcc-ws",
        repos=[
            RepoDescriptor(name="repo-a", path=repo_a),
            RepoDescriptor(name="repo-b", path=repo_b),
        ],
        links={},
    )
    WorkspaceLoader.save(tmp_path, ws)
    return tmp_path, repo_a, repo_b


# ---------------------------------------------------------------------------
# unit tests for the counter
# ---------------------------------------------------------------------------

class TestCountCrossCommunityEdges:
    def test_returns_correct_count(self, two_repo_ws):
        from core.workspace_orchestrator import _count_cross_community_edges_in_repo

        _, repo_a, _ = two_repo_ws
        db = repo_a / ".context-router" / "context-router.db"
        _seed_cross_community_edges(db, "repo-a", n_edges=7)

        count, reason = _count_cross_community_edges_in_repo(db, "repo-a")
        assert count == 7
        assert reason is None

    def test_same_community_edges_are_not_counted(self, two_repo_ws):
        from core.workspace_orchestrator import _count_cross_community_edges_in_repo

        _, repo_a, _ = two_repo_ws
        db = repo_a / ".context-router" / "context-router.db"
        _seed_cross_community_edges(db, "repo-a", n_edges=5, same_community=True)

        count, reason = _count_cross_community_edges_in_repo(db, "repo-a")
        assert count == 0
        assert reason is None

    def test_missing_db_returns_reason(self, tmp_path):
        from core.workspace_orchestrator import _count_cross_community_edges_in_repo

        missing = tmp_path / "does-not-exist.db"
        count, reason = _count_cross_community_edges_in_repo(missing, "repo-a")
        assert count == 0
        assert reason is not None and "db missing" in reason

    def test_no_community_assignments_returns_reason(self, two_repo_ws):
        """A repo with symbols but zero community_id values contributes 0
        and a skip reason (silent-failure rule: do not warn, do log)."""
        from core.workspace_orchestrator import _count_cross_community_edges_in_repo

        _, repo_a, _ = two_repo_ws
        db = repo_a / ".context-router" / "context-router.db"
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "INSERT INTO symbols(repo, file_path, name, kind) "
                "VALUES ('repo-a', 'x.py', 'x', 'function')"
            )
            conn.commit()
        finally:
            conn.close()

        count, reason = _count_cross_community_edges_in_repo(db, "repo-a")
        assert count == 0
        assert reason is not None and "community" in reason


class TestDetectAcrossWorkspace:
    def test_sum_across_repos(self, two_repo_ws):
        from core.workspace_orchestrator import _detect_cross_community_coupling

        _, repo_a, repo_b = two_repo_ws
        _seed_cross_community_edges(
            repo_a / ".context-router" / "context-router.db", "repo-a", n_edges=3
        )
        _seed_cross_community_edges(
            repo_b / ".context-router" / "context-router.db", "repo-b", n_edges=4
        )

        repos = [
            RepoDescriptor(name="repo-a", path=repo_a),
            RepoDescriptor(name="repo-b", path=repo_b),
        ]
        total, reasons = _detect_cross_community_coupling(repos)
        assert total == 7
        assert reasons == []


# ---------------------------------------------------------------------------
# end-to-end tests: stderr contains the warning only when appropriate
# ---------------------------------------------------------------------------

class TestBuildPackEmitsWarning:
    def test_warning_fires_when_count_above_threshold(
        self, two_repo_ws, capsys, monkeypatch
    ):
        from core.workspace_orchestrator import WorkspaceOrchestrator

        ws_root, repo_a, repo_b = two_repo_ws
        _seed_cross_community_edges(
            repo_a / ".context-router" / "context-router.db", "repo-a", n_edges=60
        )
        _seed_cross_community_edges(
            repo_b / ".context-router" / "context-router.db", "repo-b", n_edges=10
        )

        orch = WorkspaceOrchestrator(workspace_root=ws_root)
        orch.build_pack("review", "test")

        captured = capsys.readouterr()
        assert "cross-community edges detected" in captured.err
        assert "70" in captured.err  # total count

    def test_warning_does_not_fire_below_threshold(self, two_repo_ws, capsys):
        """With the default threshold of 50 and only 4 cross-community edges
        across both repos, no warning should be emitted."""
        from core.workspace_orchestrator import WorkspaceOrchestrator

        ws_root, repo_a, repo_b = two_repo_ws
        _seed_cross_community_edges(
            repo_a / ".context-router" / "context-router.db", "repo-a", n_edges=2
        )
        _seed_cross_community_edges(
            repo_b / ".context-router" / "context-router.db", "repo-b", n_edges=2
        )

        orch = WorkspaceOrchestrator(workspace_root=ws_root)
        orch.build_pack("review", "test")

        captured = capsys.readouterr()
        assert "cross-community edges detected" not in captured.err

    def test_single_repo_workspace_does_not_warn(self, tmp_path, capsys):
        """A workspace with a single repo must never emit the warning even
        when the number of cross-community edges exceeds the threshold —
        the outcome is scoped to multi-repo packs."""
        from core.workspace_orchestrator import WorkspaceOrchestrator

        repo = tmp_path / "only_repo"
        repo.mkdir()
        _init_repo(repo)
        _seed_cross_community_edges(
            repo / ".context-router" / "context-router.db", "only-repo", n_edges=200
        )

        ws = WorkspaceDescriptor(
            name="single",
            repos=[RepoDescriptor(name="only-repo", path=repo)],
            links={},
        )
        WorkspaceLoader.save(tmp_path, ws)

        orch = WorkspaceOrchestrator(workspace_root=tmp_path)
        orch.build_pack("review", "test")

        captured = capsys.readouterr()
        assert "cross-community edges detected" not in captured.err

    def test_threshold_respects_config_override(self, two_repo_ws, capsys):
        """When the YAML config lowers the threshold, the warning should
        fire at a smaller edge count."""
        from core.workspace_orchestrator import WorkspaceOrchestrator

        ws_root, repo_a, repo_b = two_repo_ws
        _seed_cross_community_edges(
            repo_a / ".context-router" / "context-router.db", "repo-a", n_edges=3
        )

        # Drop a config at workspace root lowering the threshold to 2.
        cfg_dir = ws_root / ".context-router"
        cfg_dir.mkdir(exist_ok=True)
        (cfg_dir / "config.yaml").write_text(
            "capabilities:\n  coupling_warn_threshold: 2\n",
            encoding="utf-8",
        )

        orch = WorkspaceOrchestrator(workspace_root=ws_root)
        orch.build_pack("review", "test")

        captured = capsys.readouterr()
        assert "cross-community edges detected" in captured.err
        assert "threshold: 2" in captured.err


# ---------------------------------------------------------------------------
# config parsing
# ---------------------------------------------------------------------------

class TestConfigField:
    def test_default_is_50(self):
        cfg = ContextRouterConfig()
        assert cfg.capabilities.coupling_warn_threshold == 50

    def test_can_override(self):
        cfg = CapabilitiesConfig(coupling_warn_threshold=17)
        assert cfg.coupling_warn_threshold == 17
