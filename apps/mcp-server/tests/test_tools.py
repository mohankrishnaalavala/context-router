"""Tests for the write-side MCP tools: save_observation and save_decision."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Initialised project root with a context-router database."""
    from cli.main import app
    from typer.testing import CliRunner

    CliRunner().invoke(app, ["init", "--project-root", str(tmp_path)])
    return tmp_path


class TestSaveObservation:
    def test_saves_basic_observation(self, project_root: Path):
        from mcp_server.tools import save_observation

        result = save_observation(
            summary="fixed login issue",
            project_root=str(project_root),
        )
        assert result["saved"] is True
        assert "id" in result

    def test_saves_observation_with_all_fields(self, project_root: Path):
        from mcp_server.tools import save_observation

        result = save_observation(
            summary="implemented caching",
            task_type="implement",
            files_touched=["cache.py", "tests/test_cache.py"],
            commands_run=["uv run pytest"],
            failures_seen=["AssertionError in test_cache"],
            fix_summary="used LRU cache with 5 min TTL",
            commit_sha="abc1234",
            project_root=str(project_root),
        )
        assert result["saved"] is True

    def test_duplicate_observation_not_saved(self, project_root: Path):
        from mcp_server.tools import save_observation

        kwargs = {
            "summary": "duplicate test",
            "task_type": "general",
            "project_root": str(project_root),
        }
        result1 = save_observation(**kwargs)
        result2 = save_observation(**kwargs)
        assert result1["saved"] is True
        assert result2["saved"] is False
        assert "duplicate" in result2["reason"]

    def test_missing_db_returns_error(self, tmp_path: Path):
        from mcp_server.tools import save_observation

        result = save_observation(
            summary="should fail",
            project_root=str(tmp_path),
        )
        assert "error" in result
        assert result.get("saved") is False

    def test_secrets_redacted_in_commands(self, project_root: Path):
        from mcp_server.tools import save_observation, search_memory

        save_observation(
            summary="secret command obs",
            task_type="commit",
            commands_run=["export API_KEY=topsecret123 && deploy.sh"],
            project_root=str(project_root),
        )
        result = search_memory("secret command obs", project_root=str(project_root))
        obs_list = result["results"]
        assert obs_list
        assert "topsecret123" not in str(obs_list[0]["commands_run"])


class TestSaveDecision:
    def test_saves_basic_decision(self, project_root: Path):
        from mcp_server.tools import save_decision

        result = save_decision(
            title="Use SQLite for local storage",
            decision="SQLite chosen over PostgreSQL for offline-first capability",
            project_root=str(project_root),
        )
        assert result["saved"] is True
        assert "id" in result

    def test_saves_decision_with_all_fields(self, project_root: Path):
        from mcp_server.tools import save_decision

        result = save_decision(
            title="Use async handlers",
            decision="All MCP handlers use asyncio.to_thread for non-blocking I/O",
            context="MCP server must handle concurrent tool calls",
            consequences="Slightly more complex error handling",
            tags=["architecture", "async", "mcp"],
            status="accepted",
            project_root=str(project_root),
        )
        assert result["saved"] is True

    def test_saved_decision_is_retrievable(self, project_root: Path):
        from mcp_server.tools import get_decisions, save_decision

        save_decision(
            title="Use pydantic for validation",
            decision="Pydantic v2 chosen for data validation",
            project_root=str(project_root),
        )
        result = get_decisions(query="pydantic", project_root=str(project_root))
        assert result["decisions"]
        assert any("pydantic" in d["title"].lower() for d in result["decisions"])

    def test_missing_db_returns_error(self, tmp_path: Path):
        from mcp_server.tools import save_decision

        result = save_decision(
            title="will fail",
            decision="no db",
            project_root=str(tmp_path),
        )
        assert "error" in result
        assert result.get("saved") is False
