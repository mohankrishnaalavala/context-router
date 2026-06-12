"""Tests for `context-router hooks install|uninstall|status` (v4.6 spec B2).

DoD `v4.6-hooks-install`:
  * install twice → byte-identical .claude/settings.json (idempotent)
  * existing user hooks / unrelated settings keys are merged, never clobbered
  * uninstall removes ONLY context-router entries, preserves everything else
  * outside a project root (no .git, no .context-router) → exit non-zero
    with a named reason
  * --global targets $HOME/.claude/settings.json (tests use a temp HOME)
  * no silent failures: every inactive path emits a named stderr message
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

MARKER = "context-router update-index"


def _project(tmp_path: Path) -> Path:
    """A directory that qualifies as a project root (.context-router)."""
    root = tmp_path / "proj"
    (root / ".context-router").mkdir(parents=True)
    return root


def _settings_path(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _our_commands(settings: dict) -> list[str]:
    found: list[str] = []
    for groups in settings.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                if MARKER in hook.get("command", ""):
                    found.append(hook["command"])
    return found


# ── install ───────────────────────────────────────────────────────────────────


class TestHooksInstall:
    def test_install_creates_settings_with_post_tool_use_entry(
        self, tmp_path: Path
    ) -> None:
        root = _project(tmp_path)
        result = runner.invoke(app, ["hooks", "install", "--project-root", str(root)])
        assert result.exit_code == 0, result.output

        settings = _load(_settings_path(root))
        groups = settings["hooks"]["PostToolUse"]
        ours = [
            g
            for g in groups
            if any(MARKER in h.get("command", "") for h in g.get("hooks", []))
        ]
        assert len(ours) == 1
        assert ours[0]["matcher"] == "Edit|Write|MultiEdit"
        hook = ours[0]["hooks"][0]
        assert hook["type"] == "command"
        # The hook command extracts the edited path from stdin JSON and
        # passes the project root explicitly.
        assert "tool_input" in hook["command"]
        assert str(root) in hook["command"]

    def test_install_is_idempotent_byte_identical(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        r1 = runner.invoke(app, ["hooks", "install", "--project-root", str(root)])
        assert r1.exit_code == 0, r1.output
        first = _settings_path(root).read_bytes()

        r2 = runner.invoke(app, ["hooks", "install", "--project-root", str(root)])
        assert r2.exit_code == 0, r2.output
        second = _settings_path(root).read_bytes()
        assert first == second

    def test_install_merges_with_existing_user_settings(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        path = _settings_path(root)
        path.parent.mkdir(parents=True)
        user_settings = {
            "permissions": {"allow": ["Bash(ls:*)"]},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "echo pre"}],
                    }
                ],
                "PostToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "echo post"}],
                    }
                ],
            },
        }
        path.write_text(json.dumps(user_settings, indent=2) + "\n")

        result = runner.invoke(app, ["hooks", "install", "--project-root", str(root)])
        assert result.exit_code == 0, result.output

        merged = _load(path)
        # Unrelated top-level keys preserved exactly
        assert merged["permissions"] == user_settings["permissions"]
        # Other events preserved exactly
        assert merged["hooks"]["PreToolUse"] == user_settings["hooks"]["PreToolUse"]
        # User's PostToolUse group preserved, ours added alongside
        post = merged["hooks"]["PostToolUse"]
        assert user_settings["hooks"]["PostToolUse"][0] in post
        assert len(_our_commands(merged)) == 1

    def test_install_outside_project_root_exits_nonzero_named(
        self, tmp_path: Path
    ) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        result = runner.invoke(app, ["hooks", "install", "--project-root", str(bare)])
        assert result.exit_code != 0
        assert "not a project root" in result.stderr
        assert not _settings_path(bare).exists()

    def test_install_with_invalid_settings_json_exits_nonzero_and_preserves_file(
        self, tmp_path: Path
    ) -> None:
        root = _project(tmp_path)
        path = _settings_path(root)
        path.parent.mkdir(parents=True)
        path.write_text("{not valid json")

        result = runner.invoke(app, ["hooks", "install", "--project-root", str(root)])
        assert result.exit_code != 0
        assert "invalid JSON" in result.stderr
        assert path.read_text() == "{not valid json"

    def test_install_global_targets_home_settings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))

        result = runner.invoke(app, ["hooks", "install", "--global"])
        assert result.exit_code == 0, result.output

        path = fake_home / ".claude" / "settings.json"
        assert path.exists()
        settings = _load(path)
        commands = _our_commands(settings)
        assert len(commands) == 1
        # Global hook cannot know the project root ahead of time — it must
        # rely on update-index auto-detection from the hook's cwd.
        assert "--project-root" not in commands[0]


# ── uninstall ─────────────────────────────────────────────────────────────────


class TestHooksUninstall:
    def test_uninstall_removes_only_our_entries(self, tmp_path: Path) -> None:
        root = _project(tmp_path)
        path = _settings_path(root)
        path.parent.mkdir(parents=True)
        user_settings = {
            "model": "opus",
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "echo post"}],
                    }
                ]
            },
        }
        path.write_text(json.dumps(user_settings, indent=2) + "\n")

        r1 = runner.invoke(app, ["hooks", "install", "--project-root", str(root)])
        assert r1.exit_code == 0, r1.output
        assert len(_our_commands(_load(path))) == 1

        r2 = runner.invoke(app, ["hooks", "uninstall", "--project-root", str(root)])
        assert r2.exit_code == 0, r2.output

        after = _load(path)
        assert _our_commands(after) == []
        # Everything that was there before install survives untouched.
        assert after == user_settings

    def test_uninstall_when_nothing_installed_exits_0_with_notice(
        self, tmp_path: Path
    ) -> None:
        root = _project(tmp_path)
        result = runner.invoke(
            app, ["hooks", "uninstall", "--project-root", str(root)]
        )
        assert result.exit_code == 0, result.output
        assert "nothing to remove" in result.stderr

    def test_uninstall_never_deletes_file_with_other_content(
        self, tmp_path: Path
    ) -> None:
        root = _project(tmp_path)
        path = _settings_path(root)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"model": "opus"}, indent=2) + "\n")

        runner.invoke(app, ["hooks", "install", "--project-root", str(root)])
        runner.invoke(app, ["hooks", "uninstall", "--project-root", str(root)])

        assert path.exists()
        assert _load(path) == {"model": "opus"}

    def test_uninstall_outside_project_root_exits_nonzero_named(
        self, tmp_path: Path
    ) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        result = runner.invoke(
            app, ["hooks", "uninstall", "--project-root", str(bare)]
        )
        assert result.exit_code != 0
        assert "not a project root" in result.stderr


# ── status ────────────────────────────────────────────────────────────────────


class TestHooksStatus:
    def test_status_reports_not_installed_then_installed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        root = _project(tmp_path)

        r1 = runner.invoke(app, ["hooks", "status", "--project-root", str(root)])
        assert r1.exit_code == 0, r1.output
        assert "not installed" in r1.output

        runner.invoke(app, ["hooks", "install", "--project-root", str(root)])

        r2 = runner.invoke(app, ["hooks", "status", "--project-root", str(root)])
        assert r2.exit_code == 0, r2.output
        assert "installed" in r2.output
        assert "project" in r2.output.lower()
        assert "global" in r2.output.lower()

    def test_status_outside_project_root_exits_0_and_reports_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setenv("HOME", str(fake_home))
        bare = tmp_path / "bare"
        bare.mkdir()

        result = runner.invoke(app, ["hooks", "status", "--project-root", str(bare)])
        assert result.exit_code == 0, result.output
        assert "global" in result.output.lower()
        assert "not a project root" in result.output + result.stderr


# ── git-only project detection ───────────────────────────────────────────────


class TestProjectRootDetection:
    def test_git_dir_alone_qualifies_as_project_root(self, tmp_path: Path) -> None:
        root = tmp_path / "gitproj"
        (root / ".git").mkdir(parents=True)
        result = runner.invoke(app, ["hooks", "install", "--project-root", str(root)])
        assert result.exit_code == 0, result.output
        assert _settings_path(root).exists()
