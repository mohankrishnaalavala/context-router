"""Tests for packages/workspace."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.models import RepoDescriptor, WorkspaceDescriptor
from workspace import WorkspaceLoader, RepoRegistry, detect_links


# ---------------------------------------------------------------------------
# WorkspaceLoader
# ---------------------------------------------------------------------------

class TestWorkspaceLoader:
    def test_load_missing_returns_none(self, tmp_path):
        assert WorkspaceLoader.load(tmp_path) is None

    def test_init_creates_file(self, tmp_path):
        ws = WorkspaceLoader.init(tmp_path, name="test-ws")
        assert (tmp_path / "workspace.yaml").exists()
        assert ws.name == "test-ws"
        assert ws.repos == []

    def test_save_round_trip(self, tmp_path):
        original = WorkspaceDescriptor(
            name="my-workspace",
            repos=[
                RepoDescriptor(name="service-a", path=tmp_path / "a"),
                RepoDescriptor(name="service-b", path=tmp_path / "b"),
            ],
            links={"service-a": ["service-b"]},
        )
        WorkspaceLoader.save(tmp_path, original)
        loaded = WorkspaceLoader.load(tmp_path)
        assert loaded is not None
        assert loaded.name == "my-workspace"
        assert len(loaded.repos) == 2
        assert loaded.links == {"service-a": ["service-b"]}

    def test_load_enriches_with_git_state(self, tmp_path):
        """Repos get branch/sha/dirty populated (possibly empty strings for non-git paths)."""
        ws = WorkspaceDescriptor(
            name="ws",
            repos=[RepoDescriptor(name="repo-a", path=tmp_path / "nonexistent")],
            links={},
        )
        WorkspaceLoader.save(tmp_path, ws)
        loaded = WorkspaceLoader.load(tmp_path)
        assert loaded is not None
        assert len(loaded.repos) == 1
        # Dirty should be False for non-existent path (graceful fallback)
        assert loaded.repos[0].dirty is False

    def test_load_invalid_yaml_returns_none(self, tmp_path):
        (tmp_path / "workspace.yaml").write_text("{{ invalid: yaml: [")
        # Should return None, not raise
        result = WorkspaceLoader.load(tmp_path)
        assert result is None


# ---------------------------------------------------------------------------
# RepoRegistry
# ---------------------------------------------------------------------------

class TestRepoRegistry:
    def _make_ws(self, repos: list[RepoDescriptor] | None = None) -> WorkspaceDescriptor:
        return WorkspaceDescriptor(name="ws", repos=repos or [], links={})

    def test_get_all_empty(self):
        reg = RepoRegistry(self._make_ws())
        assert reg.get_all() == []

    def test_add_repo(self, tmp_path):
        reg = RepoRegistry(self._make_ws())
        repo = reg.add("my-repo", tmp_path)
        assert repo.name == "my-repo"
        assert repo.path == tmp_path
        assert len(reg.get_all()) == 1

    def test_add_existing_updates(self, tmp_path):
        reg = RepoRegistry(self._make_ws())
        reg.add("my-repo", tmp_path)
        reg.add("my-repo", tmp_path, language="python")
        assert len(reg.get_all()) == 1
        assert reg.get("my-repo").language == "python"

    def test_remove_repo(self, tmp_path):
        reg = RepoRegistry(self._make_ws())
        reg.add("my-repo", tmp_path)
        reg.remove("my-repo")
        assert reg.get_all() == []

    def test_remove_missing_raises(self):
        reg = RepoRegistry(self._make_ws())
        with pytest.raises(KeyError):
            reg.remove("nonexistent")

    def test_remove_cleans_up_links(self, tmp_path):
        reg = RepoRegistry(self._make_ws())
        reg.add("a", tmp_path)
        reg.add("b", tmp_path)
        reg.add_link("a", "b")
        reg.remove("b")
        assert "b" not in reg.get_links().get("a", [])

    def test_add_link(self, tmp_path):
        reg = RepoRegistry(self._make_ws())
        reg.add("a", tmp_path)
        reg.add("b", tmp_path)
        reg.add_link("a", "b")
        assert "b" in reg.get_links()["a"]

    def test_add_link_no_duplicates(self, tmp_path):
        reg = RepoRegistry(self._make_ws())
        reg.add_link("a", "b")
        reg.add_link("a", "b")
        assert reg.get_links()["a"].count("b") == 1

    def test_refresh_does_not_crash(self, tmp_path):
        ws = WorkspaceDescriptor(
            name="ws",
            repos=[RepoDescriptor(name="r", path=tmp_path)],
            links={},
        )
        reg = RepoRegistry(ws)
        reg.refresh_git_state()  # Should not raise
        assert len(reg.get_all()) == 1

    def test_to_descriptor_round_trip(self, tmp_path):
        reg = RepoRegistry(self._make_ws())
        reg.add("r", tmp_path)
        reg.add_link("r", "other")
        desc = reg.to_descriptor()
        assert desc.name == "ws"
        assert len(desc.repos) == 1
        assert "r" in desc.links

    def test_initialise_from_existing_descriptor(self, tmp_path):
        existing = WorkspaceDescriptor(
            name="existing",
            repos=[RepoDescriptor(name="x", path=tmp_path)],
            links={"x": ["y"]},
        )
        reg = RepoRegistry(existing)
        assert reg.get("x") is not None
        assert reg.get_links() == {"x": ["y"]}


# ---------------------------------------------------------------------------
# detect_links
# ---------------------------------------------------------------------------

class TestLinkDetector:
    def test_empty_repos_returns_empty(self):
        assert detect_links([]) == {}

    def test_no_cross_imports_returns_empty(self, tmp_path):
        repo_a = tmp_path / "service_a"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("import os\nimport sys\n")
        repos = [RepoDescriptor(name="service-a", path=repo_a)]
        assert detect_links(repos) == {}

    def test_detects_direct_import(self, tmp_path):
        repo_a = tmp_path / "service_a"
        repo_b = tmp_path / "service_b"
        repo_a.mkdir()
        repo_b.mkdir()
        # service-a imports service-b (as service_b)
        (repo_a / "main.py").write_text("import service_b\n")
        (repo_b / "main.py").write_text("# nothing\n")
        repos = [
            RepoDescriptor(name="service-a", path=repo_a),
            RepoDescriptor(name="service-b", path=repo_b),
        ]
        links = detect_links(repos)
        assert "service-a" in links
        assert "service-b" in links["service-a"]

    def test_detects_from_import(self, tmp_path):
        repo_a = tmp_path / "service_a"
        repo_b = tmp_path / "service_b"
        repo_a.mkdir()
        repo_b.mkdir()
        (repo_a / "app.py").write_text("from service_b import something\n")
        repos = [
            RepoDescriptor(name="service-a", path=repo_a),
            RepoDescriptor(name="service-b", path=repo_b),
        ]
        links = detect_links(repos)
        assert "service-b" in links.get("service-a", [])

    def test_no_self_links(self, tmp_path):
        repo_a = tmp_path / "service_a"
        repo_a.mkdir()
        (repo_a / "main.py").write_text("import service_a\n")
        repos = [RepoDescriptor(name="service-a", path=repo_a)]
        links = detect_links(repos)
        assert links == {}

    def test_non_existent_path_graceful(self):
        repos = [
            RepoDescriptor(name="ghost", path=Path("/nonexistent/path/xyz")),
        ]
        assert detect_links(repos) == {}
