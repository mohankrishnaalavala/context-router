"""MCP tests for the get_minimal_context tool (Phase 3 — CRG parity)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Initialised project root with a context-router database."""
    from cli.main import app
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["init", "--project-root", str(tmp_path)])
    assert result.exit_code == 0
    return tmp_path


class TestGetMinimalContextInput:
    def test_empty_task_returns_error_code_32602(self) -> None:
        from mcp_server.tools import get_minimal_context

        result = get_minimal_context(task="")
        assert result.get("code") == -32602
        assert "empty" in result.get("error", "").lower()

    def test_whitespace_task_returns_error_code_32602(self) -> None:
        from mcp_server.tools import get_minimal_context

        result = get_minimal_context(task="   ")
        assert result.get("code") == -32602

    def test_missing_db_returns_error_without_crash(self, tmp_path: Path) -> None:
        """Uninitialised project returns a friendly error dict, not a traceback."""
        from mcp_server.tools import get_minimal_context

        result = get_minimal_context(
            task="find the ranker",
            project_root=str(tmp_path),
        )
        assert "error" in result
        # code is only set for the empty-task case; DB-missing is a plain error.
        assert result.get("code") != -32602


class TestGetMinimalContextHappyPath:
    def test_returns_context_pack_with_mode_minimal(self, project_root: Path) -> None:
        from mcp_server.tools import get_minimal_context

        result = get_minimal_context(
            task="review the ranker",
            project_root=str(project_root),
        )
        assert result.get("mode") == "minimal"
        assert "selected_items" in result
        assert len(result["selected_items"]) <= 5

    def test_sets_next_tool_suggestion(self, project_root: Path) -> None:
        from mcp_server.tools import get_minimal_context

        result = get_minimal_context(
            task="add pagination",
            project_root=str(project_root),
        )
        metadata = result.get("metadata") or {}
        assert metadata.get("next_tool_suggestion")

    def test_respects_max_tokens_argument(self, project_root: Path) -> None:
        from mcp_server.tools import get_minimal_context

        tight = get_minimal_context(
            task="scan repo",
            max_tokens=50,
            project_root=str(project_root),
        )
        loose = get_minimal_context(
            task="scan repo",
            max_tokens=5000,
            project_root=str(project_root),
        )
        # Tight total must be <= loose total (loose has at least as much room).
        assert tight.get("total_est_tokens", 0) <= max(
            loose.get("total_est_tokens", 0), 50
        )


class TestGetMinimalContextRegistered:
    def test_tool_is_registered_in_main_registry(self) -> None:
        """The MCP dispatcher exposes get_minimal_context via tools/list."""
        from mcp_server.main import _TOOLS

        assert "get_minimal_context" in _TOOLS
        spec = _TOOLS["get_minimal_context"]
        assert spec["fn"].__name__ == "get_minimal_context"
        assert spec["inputSchema"]["required"] == ["task"]
        assert "max_tokens" in spec["inputSchema"]["properties"]
