"""Unit tests for MCP tool handlers."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_db(root: Path) -> None:
    """Run context-router init in root so the DB exists."""
    subprocess.run(
        [sys.executable, "-m", "cli.main", "init", "--project-root", str(root)],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project_root(tmp_path):
    """A temp directory with an initialised context-router database."""
    subprocess.run(
        ["uv", "run", "context-router", "init", "--project-root", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# build_index / update_index
# ---------------------------------------------------------------------------

class TestBuildIndex:
    def test_no_db_returns_error(self, tmp_path):
        from mcp_server.tools import build_index
        result = build_index(project_root=str(tmp_path))
        assert "error" in result

    def test_with_db_returns_stats(self, project_root):
        from mcp_server.tools import build_index
        result = build_index(project_root=str(project_root))
        # Even an empty project should return numeric keys
        assert "files" in result
        assert "symbols" in result
        assert "edges" in result
        assert "duration_seconds" in result
        assert isinstance(result["files"], int)

    def test_errors_list_capped(self, project_root):
        from mcp_server.tools import build_index
        result = build_index(project_root=str(project_root))
        assert len(result.get("errors", [])) <= 10


class TestUpdateIndex:
    def test_no_db_returns_error(self, tmp_path):
        from mcp_server.tools import update_index
        result = update_index(changed_files=[], project_root=str(tmp_path))
        assert "error" in result

    def test_empty_changed_files(self, project_root):
        from mcp_server.tools import update_index
        result = update_index(changed_files=[], project_root=str(project_root))
        assert "files" in result
        assert result["files"] == 0


# ---------------------------------------------------------------------------
# get_context_pack / get_debug_pack
# ---------------------------------------------------------------------------

class TestGetContextPack:
    def test_missing_db_returns_error(self, tmp_path):
        from mcp_server.tools import get_context_pack
        result = get_context_pack(mode="review", project_root=str(tmp_path))
        assert "error" in result

    def test_review_mode(self, project_root):
        from mcp_server.tools import get_context_pack
        result = get_context_pack(mode="review", project_root=str(project_root))
        # No error; pack returned (may be empty for empty project)
        assert "error" not in result
        assert "mode" in result
        assert result["mode"] == "review"

    def test_implement_mode(self, project_root):
        from mcp_server.tools import get_context_pack
        result = get_context_pack(mode="implement", project_root=str(project_root))
        assert result["mode"] == "implement"

    def test_handover_mode(self, project_root):
        from mcp_server.tools import get_context_pack
        result = get_context_pack(mode="handover", project_root=str(project_root))
        assert result["mode"] == "handover"


class TestGetDebugPack:
    def test_returns_pack(self, project_root):
        from mcp_server.tools import get_debug_pack
        result = get_debug_pack(project_root=str(project_root))
        assert "error" not in result
        assert result["mode"] == "debug"

    def test_with_error_file(self, project_root, tmp_path):
        from mcp_server.tools import get_debug_pack
        err_file = tmp_path / "errors.txt"
        err_file.write_text("ERROR Something went wrong\n")
        result = get_debug_pack(
            query="test failure",
            error_file=str(err_file),
            project_root=str(project_root),
        )
        assert "error" not in result


# ---------------------------------------------------------------------------
# explain_selection
# ---------------------------------------------------------------------------

class TestExplainSelection:
    def test_no_pack_returns_error(self, project_root):
        from mcp_server.tools import explain_selection
        result = explain_selection(project_root=str(project_root))
        assert "error" in result

    def test_after_pack_returns_explanation(self, project_root):
        from mcp_server.tools import get_context_pack, explain_selection
        get_context_pack(mode="review", project_root=str(project_root))
        result = explain_selection(project_root=str(project_root))
        assert "mode" in result
        assert "items" in result


# ---------------------------------------------------------------------------
# generate_handover
# ---------------------------------------------------------------------------

class TestGenerateHandover:
    def test_returns_handover_pack(self, project_root):
        from mcp_server.tools import generate_handover
        result = generate_handover(project_root=str(project_root))
        assert "error" not in result
        assert result["mode"] == "handover"


# ---------------------------------------------------------------------------
# search_memory / get_decisions
# ---------------------------------------------------------------------------

class TestSearchMemory:
    def test_no_db_returns_error(self, tmp_path):
        from mcp_server.tools import search_memory
        result = search_memory(query="test", project_root=str(tmp_path))
        assert "error" in result

    def test_empty_results(self, project_root):
        from mcp_server.tools import search_memory
        result = search_memory(query="zzz_nonexistent", project_root=str(project_root))
        assert "results" in result
        assert result["results"] == []


class TestGetDecisions:
    def test_no_db_returns_error(self, tmp_path):
        from mcp_server.tools import get_decisions
        result = get_decisions(project_root=str(tmp_path))
        assert "error" in result

    def test_empty_store(self, project_root):
        from mcp_server.tools import get_decisions
        result = get_decisions(project_root=str(project_root))
        assert "decisions" in result
        assert result["decisions"] == []
