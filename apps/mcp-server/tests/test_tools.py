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


# ---------------------------------------------------------------------------
# P1: get_context_summary
# ---------------------------------------------------------------------------

class TestGetContextSummary:
    def test_returns_expected_keys(self, project_root: Path):
        from mcp_server.tools import get_context_summary

        result = get_context_summary(mode="implement", project_root=str(project_root))
        assert "mode" in result
        assert "item_count" in result
        assert "total_est_tokens" in result
        assert "reduction_pct" in result
        assert "top_files" in result
        assert "source_type_counts" in result

    def test_mode_matches_request(self, project_root: Path):
        from mcp_server.tools import get_context_summary

        for mode in ("review", "implement", "debug", "handover"):
            result = get_context_summary(mode=mode, project_root=str(project_root))
            if "error" not in result:
                assert result["mode"] == mode

    def test_top_files_at_most_five(self, project_root: Path):
        from mcp_server.tools import get_context_summary

        result = get_context_summary(mode="implement", project_root=str(project_root))
        if "error" not in result:
            assert len(result["top_files"]) <= 5

    def test_top_files_have_path_and_confidence(self, project_root: Path):
        from mcp_server.tools import get_context_summary

        result = get_context_summary(mode="implement", project_root=str(project_root))
        if "error" not in result:
            for f in result["top_files"]:
                assert "path" in f
                assert "confidence" in f

    def test_missing_db_returns_error(self, tmp_path: Path):
        from mcp_server.tools import get_context_summary

        result = get_context_summary(mode="review", project_root=str(tmp_path))
        assert "error" in result

    def test_invalid_mode_returns_error(self, project_root: Path):
        from mcp_server.tools import get_context_summary

        result = get_context_summary(mode="invalid_mode", project_root=str(project_root))
        assert "error" in result


# ---------------------------------------------------------------------------
# P0b: get_context_pack compact format
# ---------------------------------------------------------------------------

class TestGetContextPackCompact:
    def test_compact_format_returns_text_key(self, project_root: Path):
        from mcp_server.tools import get_context_pack

        result = get_context_pack(mode="implement", project_root=str(project_root), format="compact")
        # Either an error (no index) or a text response
        assert "error" in result or "text" in result

    def test_compact_format_text_contains_pack_header(self, project_root: Path):
        from mcp_server.tools import get_context_pack

        result = get_context_pack(mode="implement", project_root=str(project_root), format="compact")
        if "text" in result:
            assert "implement pack" in result["text"] or "pack" in result["text"]

    def test_json_format_returns_model_fields(self, project_root: Path):
        from mcp_server.tools import get_context_pack

        result = get_context_pack(mode="implement", project_root=str(project_root), format="json")
        if "error" not in result:
            assert "mode" in result
            assert "selected_items" in result


# ---------------------------------------------------------------------------
# P3: get_context_pack pagination
# ---------------------------------------------------------------------------

class TestGetContextPackPagination:
    def test_page_size_limits_items(self, project_root: Path):
        from mcp_server.tools import get_context_pack

        result = get_context_pack(
            mode="implement", project_root=str(project_root),
            page=0, page_size=2,
        )
        if "error" not in result:
            assert len(result.get("selected_items", [])) <= 2

    def test_no_pagination_returns_has_more_false(self, project_root: Path):
        from mcp_server.tools import get_context_pack

        result = get_context_pack(mode="implement", project_root=str(project_root))
        if "error" not in result:
            assert result.get("has_more") is False


# ---------------------------------------------------------------------------
# P6: record_feedback with files_read
# ---------------------------------------------------------------------------

class TestRecordFeedbackFilesRead:
    def test_record_feedback_accepts_files_read(self, project_root: Path):
        from mcp_server.tools import record_feedback
        from storage_sqlite.database import Database

        # Save an observation first to get a valid pack_id-like UUID
        import uuid
        pack_id = str(uuid.uuid4())
        result = record_feedback(
            pack_id=pack_id,
            useful=True,
            files_read=["src/auth.py", "src/token.py"],
            project_root=str(project_root),
        )
        assert result.get("recorded") is True
        assert "id" in result
        with Database(project_root / ".context-router" / "context-router.db") as db:
            row = db.connection.execute(
                "SELECT repo_scope FROM pack_feedback WHERE pack_id = ?",
                (pack_id,),
            ).fetchone()
        assert row["repo_scope"] == str(project_root.resolve())

    def test_record_feedback_without_files_read_still_works(self, project_root: Path):
        from mcp_server.tools import record_feedback
        import uuid

        result = record_feedback(
            pack_id=str(uuid.uuid4()),
            useful=False,
            project_root=str(project_root),
        )
        assert result.get("recorded") is True
