"""CLI tests for 'context-router workspace' commands."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def _cr(*args, **kwargs):
    """Invoke the CLI with given args."""
    return runner.invoke(app, list(args), catch_exceptions=False, **kwargs)


def _init_repo(path: Path) -> None:
    """Create .context-router/ in path so workspace pack doesn't error."""
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(path)],
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# workspace init
# ---------------------------------------------------------------------------

class TestWorkspaceInit:
    def test_creates_workspace_yaml(self, tmp_path):
        result = _cr("workspace", "init", "--root", str(tmp_path))
        assert result.exit_code == 0
        assert (tmp_path / "workspace.yaml").exists()

    def test_default_name(self, tmp_path):
        _cr("workspace", "init", "--root", str(tmp_path))
        # Load and check name
        from workspace import WorkspaceLoader
        ws = WorkspaceLoader.load(tmp_path)
        assert ws is not None
        assert ws.name == "default"

    def test_custom_name(self, tmp_path):
        _cr("workspace", "init", "--root", str(tmp_path), "--name", "my-ws")
        from workspace import WorkspaceLoader
        ws = WorkspaceLoader.load(tmp_path)
        assert ws.name == "my-ws"

    def test_already_exists_exits_1(self, tmp_path):
        _cr("workspace", "init", "--root", str(tmp_path))
        result = _cr("workspace", "init", "--root", str(tmp_path))
        assert result.exit_code == 1

    def test_json_output(self, tmp_path):
        result = _cr("workspace", "init", "--root", str(tmp_path), "--json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "name" in data
        assert "path" in data


# ---------------------------------------------------------------------------
# workspace repo add
# ---------------------------------------------------------------------------

class TestRepoAdd:
    def test_adds_repo(self, tmp_path):
        repo_dir = tmp_path / "svc"
        repo_dir.mkdir()
        _cr("workspace", "init", "--root", str(tmp_path))
        result = _cr(
            "workspace", "repo", "add",
            "svc", str(repo_dir),
            "--root", str(tmp_path),
            "--no-detect-links",
        )
        assert result.exit_code == 0
        from workspace import WorkspaceLoader
        ws = WorkspaceLoader.load(tmp_path)
        assert any(r.name == "svc" for r in ws.repos)

    def test_json_output(self, tmp_path):
        repo_dir = tmp_path / "svc"
        repo_dir.mkdir()
        _cr("workspace", "init", "--root", str(tmp_path))
        result = _cr(
            "workspace", "repo", "add",
            "svc", str(repo_dir),
            "--root", str(tmp_path),
            "--no-detect-links",
            "--json",
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "svc"

    def test_no_workspace_yaml_exits_1(self, tmp_path):
        result = _cr(
            "workspace", "repo", "add",
            "svc", str(tmp_path),
            "--root", str(tmp_path),
        )
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# workspace repo list
# ---------------------------------------------------------------------------

class TestRepoList:
    def test_empty_workspace(self, tmp_path):
        _cr("workspace", "init", "--root", str(tmp_path))
        result = _cr("workspace", "repo", "list", "--root", str(tmp_path))
        assert result.exit_code == 0
        assert "No repos" in result.output

    def test_lists_added_repos(self, tmp_path):
        repo_a = tmp_path / "a"
        repo_a.mkdir()
        _cr("workspace", "init", "--root", str(tmp_path))
        _cr(
            "workspace", "repo", "add", "service-a", str(repo_a),
            "--root", str(tmp_path), "--no-detect-links",
        )
        result = _cr("workspace", "repo", "list", "--root", str(tmp_path))
        assert result.exit_code == 0
        assert "service-a" in result.output

    def test_json_output(self, tmp_path):
        repo_a = tmp_path / "a"
        repo_a.mkdir()
        _cr("workspace", "init", "--root", str(tmp_path))
        _cr(
            "workspace", "repo", "add", "svc", str(repo_a),
            "--root", str(tmp_path), "--no-detect-links",
        )
        result = _cr("workspace", "repo", "list", "--root", str(tmp_path), "--json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert data[0]["name"] == "svc"

    def test_no_workspace_yaml_exits_1(self, tmp_path):
        result = _cr("workspace", "repo", "list", "--root", str(tmp_path))
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# workspace link add
# ---------------------------------------------------------------------------

class TestLinkAdd:
    def test_adds_link(self, tmp_path):
        _cr("workspace", "init", "--root", str(tmp_path))
        result = _cr(
            "workspace", "link", "add",
            "service-a", "service-b",
            "--root", str(tmp_path),
        )
        assert result.exit_code == 0
        from workspace import WorkspaceLoader
        ws = WorkspaceLoader.load(tmp_path)
        assert "service-b" in ws.links.get("service-a", [])

    def test_json_output(self, tmp_path):
        _cr("workspace", "init", "--root", str(tmp_path))
        result = _cr(
            "workspace", "link", "add",
            "a", "b",
            "--root", str(tmp_path),
            "--json",
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == {"from": "a", "to": "b"}


# ---------------------------------------------------------------------------
# workspace pack
# ---------------------------------------------------------------------------

class TestWorkspacePack:
    def test_no_workspace_exits_1(self, tmp_path):
        result = _cr("workspace", "pack", "--mode", "review", "--root", str(tmp_path))
        assert result.exit_code == 1

    def test_invalid_mode_exits_2(self, tmp_path):
        _cr("workspace", "init", "--root", str(tmp_path))
        result = _cr("workspace", "pack", "--mode", "bogus", "--root", str(tmp_path))
        assert result.exit_code == 2

    def test_empty_workspace_returns_no_items(self, tmp_path):
        """Workspace with no repos produces an empty pack (exit 0)."""
        _cr("workspace", "init", "--root", str(tmp_path))
        result = _cr("workspace", "pack", "--mode", "review", "--root", str(tmp_path))
        assert result.exit_code == 0

    def test_json_output_valid(self, tmp_path):
        repo_a = tmp_path / "repo_a"
        repo_a.mkdir()
        _init_repo(repo_a)
        _cr("workspace", "init", "--root", str(tmp_path))
        _cr(
            "workspace", "repo", "add", "repo-a", str(repo_a),
            "--root", str(tmp_path), "--no-detect-links",
        )
        result = _cr(
            "workspace", "pack",
            "--mode", "review",
            "--root", str(tmp_path),
            "--json",
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["mode"] == "review"
        assert "selected_items" in data
