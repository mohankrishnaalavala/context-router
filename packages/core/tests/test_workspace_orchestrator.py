"""Tests for WorkspaceOrchestrator."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from contracts.models import ContextItem, ContextPack, RepoDescriptor, WorkspaceDescriptor
from workspace import WorkspaceLoader


def _init_repo(path: Path) -> None:
    """Run context-router init in a temp directory so the DB exists."""
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(path)],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def workspace_root(tmp_path):
    """A temp directory with workspace.yaml referencing two initialised repos."""
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    _init_repo(repo_a)
    _init_repo(repo_b)

    ws = WorkspaceDescriptor(
        name="test-ws",
        repos=[
            RepoDescriptor(name="repo-a", path=repo_a),
            RepoDescriptor(name="repo-b", path=repo_b),
        ],
        links={"repo-a": ["repo-b"]},
    )
    WorkspaceLoader.save(tmp_path, ws)
    return tmp_path, repo_a, repo_b


# ---------------------------------------------------------------------------
# WorkspaceOrchestrator basics
# ---------------------------------------------------------------------------

class TestWorkspaceOrchestratorInit:
    def test_no_workspace_yaml_raises(self, tmp_path):
        from core.workspace_orchestrator import WorkspaceOrchestrator
        orch = WorkspaceOrchestrator(workspace_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="workspace.yaml"):
            orch.build_pack("review", "test")

    def test_unknown_mode_raises(self, workspace_root):
        from core.workspace_orchestrator import WorkspaceOrchestrator
        ws_root, _, _ = workspace_root
        orch = WorkspaceOrchestrator(workspace_root=ws_root)
        with pytest.raises(ValueError, match="Unknown mode"):
            orch.build_pack("nonexistent_mode", "test")


class TestWorkspacePackGeneration:
    def test_returns_context_pack(self, workspace_root):
        from core.workspace_orchestrator import WorkspaceOrchestrator
        ws_root, _, _ = workspace_root
        orch = WorkspaceOrchestrator(workspace_root=ws_root)
        pack = orch.build_pack("review", "test query")
        assert isinstance(pack, ContextPack)
        assert pack.mode == "review"

    def test_all_modes_work(self, workspace_root):
        from core.workspace_orchestrator import WorkspaceOrchestrator
        ws_root, _, _ = workspace_root
        orch = WorkspaceOrchestrator(workspace_root=ws_root)
        for mode in ("review", "implement", "debug", "handover"):
            pack = orch.build_pack(mode, "")
            assert pack.mode == mode

    def test_saves_last_pack(self, workspace_root):
        from core.workspace_orchestrator import WorkspaceOrchestrator
        ws_root, _, _ = workspace_root
        orch = WorkspaceOrchestrator(workspace_root=ws_root)
        orch.build_pack("review", "test")
        last_pack_path = ws_root / ".context-router" / "last-pack.json"
        assert last_pack_path.exists()

    def test_last_pack_returns_none_before_run(self, tmp_path):
        from core.workspace_orchestrator import WorkspaceOrchestrator
        WorkspaceLoader.init(tmp_path)
        orch = WorkspaceOrchestrator(workspace_root=tmp_path)
        assert orch.last_pack() is None

    def test_last_pack_after_run(self, workspace_root):
        from core.workspace_orchestrator import WorkspaceOrchestrator
        ws_root, _, _ = workspace_root
        orch = WorkspaceOrchestrator(workspace_root=ws_root)
        orch.build_pack("implement", "test")
        loaded = orch.last_pack()
        assert loaded is not None
        assert loaded.mode == "implement"

    def test_skips_uninitialised_repos(self, tmp_path):
        """Repos without a DB are skipped, not raised as errors."""
        from core.workspace_orchestrator import WorkspaceOrchestrator

        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        # repo_a has no DB

        ws = WorkspaceDescriptor(
            name="ws",
            repos=[RepoDescriptor(name="repo-a", path=repo_a)],
            links={},
        )
        WorkspaceLoader.save(tmp_path, ws)

        orch = WorkspaceOrchestrator(workspace_root=tmp_path)
        pack = orch.build_pack("review", "test")
        assert isinstance(pack, ContextPack)
        assert pack.selected_items == []


# ---------------------------------------------------------------------------
# Link boost
# ---------------------------------------------------------------------------

class TestLinkBoost:
    def test_boost_increases_confidence(self):
        from core.workspace_orchestrator import _boost_linked_items

        item = ContextItem(
            source_type="file",
            repo="repo-b",
            path_or_ref="foo.py",
            title="Foo",
            reason="",
            confidence=0.5,
            est_tokens=10,
        )
        links = {"repo-a": ["repo-b"]}
        boosted = _boost_linked_items([item], links)
        assert boosted[0].confidence > item.confidence

    def test_boost_capped_at_max(self):
        from core.workspace_orchestrator import _MAX_CONFIDENCE, _boost_linked_items

        item = ContextItem(
            source_type="file",
            repo="repo-b",
            path_or_ref="foo.py",
            title="Foo",
            reason="",
            confidence=0.95,
            est_tokens=10,
        )
        links = {"repo-a": ["repo-b"]}
        boosted = _boost_linked_items([item], links)
        assert boosted[0].confidence <= _MAX_CONFIDENCE

    def test_unlinked_repo_not_boosted(self):
        from core.workspace_orchestrator import _boost_linked_items

        item = ContextItem(
            source_type="file",
            repo="standalone",
            path_or_ref="foo.py",
            title="Foo",
            reason="",
            confidence=0.5,
            est_tokens=10,
        )
        links = {"repo-a": ["repo-b"]}
        boosted = _boost_linked_items([item], links)
        assert boosted[0].confidence == item.confidence

    def test_no_links_no_change(self):
        from core.workspace_orchestrator import _boost_linked_items

        item = ContextItem(
            source_type="file",
            repo="r",
            path_or_ref="f.py",
            title="T",
            reason="",
            confidence=0.6,
            est_tokens=5,
        )
        result = _boost_linked_items([item], {})
        assert result[0].confidence == item.confidence


# ---------------------------------------------------------------------------
# Title prefixing
# ---------------------------------------------------------------------------

class TestTitlePrefix:
    def test_prefix_added(self):
        from core.workspace_orchestrator import _prefix_title
        item = ContextItem(
            source_type="file",
            repo="r",
            path_or_ref="f.py",
            title="My Function",
            reason="",
            confidence=0.5,
            est_tokens=5,
        )
        prefixed = _prefix_title(item, "service-a")
        assert prefixed.title == "[service-a] My Function"

    def test_no_duplicate_prefix(self):
        from core.workspace_orchestrator import _prefix_title
        item = ContextItem(
            source_type="file",
            repo="r",
            path_or_ref="f.py",
            title="[service-a] My Function",
            reason="",
            confidence=0.5,
            est_tokens=5,
        )
        prefixed = _prefix_title(item, "service-a")
        assert prefixed.title.count("[service-a]") == 1


# ---------------------------------------------------------------------------
# WorkspaceStore-backed cross-repo edges
# ---------------------------------------------------------------------------

class TestWorkspaceDbBackedBoost:
    def test_reads_edges_from_workspace_db(self, tmp_path):
        from workspace_store.store import CrossRepoEdge, RepoRecord, WorkspaceStore

        db = tmp_path / ".context-router" / "workspace.db"
        store = WorkspaceStore.open(db)
        store.register_repo(RepoRecord(repo_id="a", name="a", root=str(tmp_path / "a")))
        store.register_repo(RepoRecord(repo_id="b", name="b", root=str(tmp_path / "b")))
        store.replace_edges_for_src("a", [CrossRepoEdge(
            src_repo_id="a", src_symbol_id=None, src_file="src/x.ts",
            dst_repo_id="b", dst_symbol_id=None, dst_file="src/y.py",
            edge_kind="consumes_openapi", confidence=0.9,
        )])
        store.close()

        from core.workspace_orchestrator import WorkspaceOrchestrator
        orch = WorkspaceOrchestrator(workspace_root=tmp_path)
        linked = orch.cross_repo_edges_for_repo("a")
        assert any(e.dst_file == "src/y.py" for e in linked)
