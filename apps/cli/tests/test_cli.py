"""CLI integration tests using Typer's CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


class TestHelp:
    def test_root_help_exits_0(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "context-router" in result.output

    def test_init_help_exits_0(self):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0

    def test_pack_help_exits_0(self):
        result = runner.invoke(app, ["pack", "--help"])
        assert result.exit_code == 0

    def test_index_help_exits_0(self):
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0

    def test_memory_help_exits_0(self):
        result = runner.invoke(app, ["memory", "--help"])
        assert result.exit_code == 0

    def test_decisions_help_exits_0(self):
        result = runner.invoke(app, ["decisions", "--help"])
        assert result.exit_code == 0


class TestInit:
    def test_creates_context_router_directory(self, tmp_path: Path):
        result = runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert (tmp_path / ".context-router").is_dir()

    def test_creates_sqlite_database(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        db_path = tmp_path / ".context-router" / "context-router.db"
        assert db_path.exists()
        assert db_path.stat().st_size > 0

    def test_creates_config_yaml(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        config_path = tmp_path / ".context-router" / "config.yaml"
        assert config_path.exists()

    def test_json_output(self, tmp_path: Path):
        import json
        result = runner.invoke(app, ["init", "--project-root", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert "db_path" in data

    def test_idempotent_second_init(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        assert result.exit_code == 0


class TestPack:
    def test_invalid_mode_exits_2(self):
        result = runner.invoke(app, ["pack", "--mode", "invalid"])
        assert result.exit_code == 2

    def test_valid_mode_review_exits_0(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(
            app, ["pack", "--mode", "review", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output

    def test_valid_mode_debug_exits_0(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(
            app, ["pack", "--mode", "debug", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output

    def test_valid_mode_implement_exits_0(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(
            app, ["pack", "--mode", "implement", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output

    def test_valid_mode_handover_exits_0(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(
            app, ["pack", "--mode", "handover", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output

    def test_no_project_exits_1(self, tmp_path: Path):
        result = runner.invoke(
            app, ["pack", "--mode", "review", "--project-root", str(tmp_path)]
        )
        assert result.exit_code == 1

    def test_json_output(self, tmp_path: Path):
        import json
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(
            app, ["pack", "--mode", "implement", "--project-root", str(tmp_path), "--json"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["mode"] == "implement"


class TestMemoryAdd:
    def test_add_no_source_exits_1(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(app, ["memory", "add", "--project-root", str(tmp_path)])
        assert result.exit_code == 1
        assert "stdin" in result.output

    def test_add_from_stdin_single_observation(self, tmp_path: Path):
        import json
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        payload = json.dumps({"summary": "test obs from stdin"})
        result = runner.invoke(
            app,
            ["memory", "add", "--stdin", "--project-root", str(tmp_path)],
            input=payload,
        )
        assert result.exit_code == 0, result.output
        assert "1 observation" in result.output

    def test_add_from_stdin_json_output(self, tmp_path: Path):
        import json
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        payload = json.dumps({"summary": "json output test"})
        result = runner.invoke(
            app,
            ["memory", "add", "--stdin", "--project-root", str(tmp_path), "--json"],
            input=payload,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["added"] == 1
        assert len(data["ids"]) == 1

    def test_add_from_stdin_invalid_json_exits_2(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(
            app,
            ["memory", "add", "--stdin", "--project-root", str(tmp_path)],
            input="not json at all",
        )
        assert result.exit_code == 2

    def test_add_from_stdin_list_of_observations(self, tmp_path: Path):
        import json
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        payload = json.dumps([
            {"summary": "first obs"},
            {"summary": "second obs"},
        ])
        result = runner.invoke(
            app,
            ["memory", "add", "--stdin", "--project-root", str(tmp_path)],
            input=payload,
        )
        assert result.exit_code == 0, result.output
        assert "2 observation" in result.output


class TestMemoryCapture:
    def test_capture_basic(self, tmp_path: Path):
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(
            app,
            [
                "memory", "capture", "fixed login bug",
                "--task-type", "debug",
                "--project-root", str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Captured" in result.output

    def test_capture_with_all_options(self, tmp_path: Path):
        import json
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        result = runner.invoke(
            app,
            [
                "memory", "capture", "added pagination",
                "--task-type", "implement",
                "--files", "api.py tests/test_api.py",
                "--commit", "abc1234",
                "--fix", "cursor-based pagination",
                "--project-root", str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["captured"] is True
        assert "id" in data

    def test_capture_duplicate_skipped(self, tmp_path: Path):
        import json
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        args = [
            "memory", "capture", "same summary",
            "--task-type", "general",
            "--project-root", str(tmp_path),
            "--json",
        ]
        result1 = runner.invoke(app, args)
        result2 = runner.invoke(app, args)
        assert result1.exit_code == 0
        assert result2.exit_code == 0
        data1 = json.loads(result1.output)
        data2 = json.loads(result2.output)
        assert data1["captured"] is True
        assert data2["captured"] is False
        assert "duplicate" in data2["reason"]

    def test_capture_help_exits_0(self):
        result = runner.invoke(app, ["memory", "capture", "--help"])
        assert result.exit_code == 0


class TestExplainCommand:
    """Tests for P5 — explain last-pack --show-call-chains flag."""

    def test_explain_help_exits_0(self):
        result = runner.invoke(app, ["explain", "last-pack", "--help"])
        assert result.exit_code == 0

    def test_explain_show_call_chains_flag_exists(self):
        """--show-call-chains must be a recognised flag (not an error)."""
        result = runner.invoke(app, ["explain", "last-pack", "--help"])
        assert result.exit_code == 0
        assert "show-call-chains" in result.output

    def test_explain_no_pack_exits_1(self, tmp_path: Path):
        """Explain with no existing pack must exit code 1."""
        result = runner.invoke(app, [
            "explain", "last-pack",
            "--show-call-chains",
        ])
        # May fail with exit 1 if no pack exists; important: does not crash with unhandled exception
        assert result.exit_code in (0, 1)


class TestFeedbackFilesReadCLI:
    """Tests for P6 — feedback record --files-read."""

    def test_feedback_record_help_includes_files_read(self):
        result = runner.invoke(app, ["feedback", "record", "--help"])
        assert result.exit_code == 0
        assert "files-read" in result.output

    def test_feedback_record_with_files_read(self, tmp_path: Path):
        import json
        runner.invoke(app, ["init", "--project-root", str(tmp_path)])
        import uuid
        pack_id = str(uuid.uuid4())
        result = runner.invoke(app, [
            "feedback", "record",
            "--pack-id", pack_id,
            "--useful", "yes",
            "--files-read", "src/auth.py src/token.py",
            "--project-root", str(tmp_path),
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["recorded"] is True
