"""Tests for context-router setup command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()

# ── helpers ───────────────────────────────────────────────────────────────────

MARKER = "<!-- context-router: setup v2 -->"
LEGACY_MARKER = "<!-- context-router: setup -->"


def _init_root(tmp_path: Path) -> Path:
    """Ensure the project has a .context-router dir (simulates post-init state)."""
    (tmp_path / ".context-router").mkdir()
    return tmp_path


# ── help ──────────────────────────────────────────────────────────────────────


class TestSetupHelp:
    def test_help_exits_0(self):
        result = runner.invoke(app, ["setup", "--help"])
        assert result.exit_code == 0
        assert "setup" in result.output.lower() or "agent" in result.output.lower()


# ── auto-detection ────────────────────────────────────────────────────────────


class TestAgentDetection:
    def test_claude_detected_from_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# Instructions\n")
        result = runner.invoke(app, ["setup", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "claude" in result.output

    def test_claude_detected_from_mcp_json(self, tmp_path):
        (tmp_path / ".mcp.json").write_text('{"mcpServers":{}}')
        result = runner.invoke(app, ["setup", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "claude" in result.output

    def test_copilot_detected_from_instructions_file(self, tmp_path):
        gh = tmp_path / ".github"
        gh.mkdir()
        (gh / "copilot-instructions.md").write_text("# Copilot\n")
        result = runner.invoke(app, ["setup", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "copilot" in result.output

    def test_cursor_detected_from_cursorrules(self, tmp_path):
        (tmp_path / ".cursorrules").write_text("# Rules\n")
        result = runner.invoke(app, ["setup", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "cursor" in result.output

    def test_windsurf_detected_from_windsurfrules(self, tmp_path):
        (tmp_path / ".windsurfrules").write_text("# Rules\n")
        result = runner.invoke(app, ["setup", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "windsurf" in result.output

    def test_codex_detected_from_agents_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Agents\n")
        result = runner.invoke(app, ["setup", "--project-root", str(tmp_path)])
        assert result.exit_code == 0
        assert "codex" in result.output

    def test_no_detection_exits_1(self, tmp_path):
        result = runner.invoke(app, ["setup", "--project-root", str(tmp_path)])
        assert result.exit_code == 1
        assert "No agent" in result.output or "no agent" in result.output.lower()


# ── explicit --agent flag ─────────────────────────────────────────────────────


class TestExplicitAgent:
    def test_invalid_agent_exits_1(self, tmp_path):
        result = runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "vscode"]
        )
        assert result.exit_code == 1
        assert "Unknown agent" in result.output or "unknown" in result.output.lower()

    def test_agent_all_configures_every_agent(self, tmp_path):
        result = runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "all"]
        )
        assert result.exit_code == 0
        for agent in ("claude", "copilot", "cursor", "windsurf", "codex"):
            assert agent in result.output


# ── Claude: .mcp.json ─────────────────────────────────────────────────────────


class TestClaudeMcp:
    def test_creates_mcp_json_when_absent(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        mcp_path = tmp_path / ".mcp.json"
        assert mcp_path.exists()
        data = json.loads(mcp_path.read_text())
        assert "context-router" in data["mcpServers"]
        assert data["mcpServers"]["context-router"]["command"] == "context-router"
        assert data["mcpServers"]["context-router"]["args"] == ["mcp"]

    def test_merges_into_existing_mcp_json(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(
            json.dumps({"mcpServers": {"other-tool": {"command": "other"}}})
        )
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        data = json.loads(mcp_path.read_text())
        assert "context-router" in data["mcpServers"]
        assert "other-tool" in data["mcpServers"]

    def test_skips_mcp_json_if_already_registered(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "context-router": {"command": "context-router", "args": ["mcp"]}
                    }
                }
            )
        )
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        # File should not change (no new entry)
        data = json.loads(mcp_path.read_text())
        assert len(data["mcpServers"]) == 1


# ── Claude: CLAUDE.md ─────────────────────────────────────────────────────────


class TestClaudeMd:
    def test_creates_claude_md_when_absent(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert MARKER in content
        assert "context-router" in content

    def test_appends_to_existing_claude_md(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Existing instructions\n\nSome content.\n")
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        content = claude_md.read_text()
        assert "# Existing instructions" in content
        assert MARKER in content

    def test_idempotent_does_not_double_append(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        content = (tmp_path / "CLAUDE.md").read_text()
        assert content.count(MARKER) == 1


# ── Copilot ───────────────────────────────────────────────────────────────────


class TestCopilot:
    def test_creates_copilot_instructions(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "copilot"]
        )
        target = tmp_path / ".github" / "copilot-instructions.md"
        assert target.exists()
        assert MARKER in target.read_text()

    def test_creates_github_dir_if_missing(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "copilot"]
        )
        assert (tmp_path / ".github").is_dir()

    def test_idempotent(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "copilot"]
        )
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "copilot"]
        )
        content = (tmp_path / ".github" / "copilot-instructions.md").read_text()
        assert content.count(MARKER) == 1


# ── Cursor ────────────────────────────────────────────────────────────────────


class TestCursor:
    def test_creates_cursorrules(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "cursor"]
        )
        target = tmp_path / ".cursorrules"
        assert target.exists()
        assert MARKER in target.read_text()

    def test_appends_to_existing_cursorrules(self, tmp_path):
        (tmp_path / ".cursorrules").write_text("# My rules\n")
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "cursor"]
        )
        content = (tmp_path / ".cursorrules").read_text()
        assert "# My rules" in content
        assert MARKER in content

    def test_idempotent(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "cursor"]
        )
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "cursor"]
        )
        assert (tmp_path / ".cursorrules").read_text().count(MARKER) == 1


# ── Windsurf ──────────────────────────────────────────────────────────────────


class TestWindsurf:
    def test_creates_windsurfrules(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "windsurf"]
        )
        target = tmp_path / ".windsurfrules"
        assert target.exists()
        assert MARKER in target.read_text()

    def test_idempotent(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "windsurf"]
        )
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "windsurf"]
        )
        assert (tmp_path / ".windsurfrules").read_text().count(MARKER) == 1


# ── Codex ─────────────────────────────────────────────────────────────────────


class TestCodex:
    def test_creates_agents_md(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "codex"]
        )
        target = tmp_path / "AGENTS.md"
        assert target.exists()
        assert MARKER in target.read_text()

    def test_appends_to_existing_agents_md(self, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# Existing\n")
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "codex"]
        )
        content = (tmp_path / "AGENTS.md").read_text()
        assert "# Existing" in content
        assert MARKER in content

    def test_idempotent(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "codex"]
        )
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "codex"]
        )
        assert (tmp_path / "AGENTS.md").read_text().count(MARKER) == 1


# ── upgrade path ──────────────────────────────────────────────────────────────


class TestUpgrade:
    """Cover the --upgrade flag: replaces legacy + v2 blocks in-place."""

    LEGACY_BLOCK = (
        "\n## context-router <!-- context-router: setup -->\n\n"
        "Old guidance from a previous release.\n"
        "Use context-router for stuff.\n"
    )

    def test_upgrade_replaces_legacy_block_in_claude_md(self, tmp_path):
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("# Project\n\nUser content.\n" + self.LEGACY_BLOCK)
        result = runner.invoke(
            app,
            [
                "setup",
                "--project-root",
                str(tmp_path),
                "--agent",
                "claude",
                "--upgrade",
            ],
        )
        assert result.exit_code == 0
        text = claude.read_text()
        # Legacy single-line marker is gone; v2 bracketed pair is present.
        assert LEGACY_MARKER not in text
        assert MARKER in text
        assert "<!-- /context-router: setup v2 -->" in text
        # User content is preserved.
        assert "# Project" in text
        assert "User content." in text

    def test_upgrade_refreshes_v2_block(self, tmp_path):
        runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        result = runner.invoke(
            app,
            ["setup", "--project-root", str(tmp_path), "--agent", "claude", "--upgrade"],
        )
        assert result.exit_code == 0
        text = (tmp_path / "CLAUDE.md").read_text()
        # Single managed block remains — refresh did not duplicate it.
        assert text.count(MARKER) == 1
        assert text.count("<!-- /context-router: setup v2 -->") == 1

    def test_no_upgrade_skips_existing(self, tmp_path):
        claude = tmp_path / "CLAUDE.md"
        claude.write_text("# Existing\n\n" + self.LEGACY_BLOCK)
        result = runner.invoke(
            app, ["setup", "--project-root", str(tmp_path), "--agent", "claude"]
        )
        assert result.exit_code == 0
        # Without --upgrade, the legacy block survives untouched.
        assert LEGACY_MARKER in claude.read_text()
        assert MARKER not in claude.read_text()


# ── dry-run ───────────────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_writes_nothing(self, tmp_path):
        runner.invoke(
            app,
            ["setup", "--project-root", str(tmp_path), "--agent", "all", "--dry-run"],
        )
        # No files should have been created
        assert not (tmp_path / "CLAUDE.md").exists()
        assert not (tmp_path / ".mcp.json").exists()
        assert not (tmp_path / ".cursorrules").exists()
        assert not (tmp_path / ".windsurfrules").exists()
        assert not (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / ".github" / "copilot-instructions.md").exists()

    def test_dry_run_output_mentions_dry_run(self, tmp_path):
        result = runner.invoke(
            app,
            ["setup", "--project-root", str(tmp_path), "--agent", "claude", "--dry-run"],
        )
        assert result.exit_code == 0
        assert "dry" in result.output.lower()
