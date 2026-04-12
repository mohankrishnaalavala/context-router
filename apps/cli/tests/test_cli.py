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
