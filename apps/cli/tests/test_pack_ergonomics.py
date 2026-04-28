"""v3.3.0 lane β — CLI ergonomics tests.

Covers (one test class per item):

  * β1 — token_budget precedence: CLI > env > config.yaml > default, with
    a stderr advisory when the CLI flag overrides a lower config value.
  * β2 — review-mode sane defaults: ``--top-k 5 --max-tokens 4000`` apply
    automatically when the user did NOT pass either flag, plus a single
    stderr advisory per invocation.
  * β4 — ``--format agent`` emits a JSON array of ``{path, lines, reason}``
    and warns in handover mode (silent no-op banned).
"""

from __future__ import annotations

import json
from pathlib import Path

from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def _init(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", "--project-root", str(tmp_path)])
    assert result.exit_code == 0, result.output


def _write_config(root: Path, token_budget: int) -> None:
    cfg_dir = root / ".context-router"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        f"token_budget: {token_budget}\n"
        "capabilities:\n  llm_summarization: false\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# β1 — token_budget precedence
# ---------------------------------------------------------------------------


class TestTokenBudgetPrecedence:
    """``--max-tokens`` must override config and emit a visible advisory."""

    def test_cli_flag_overrides_lower_config_prints_advisory(
        self, tmp_path: Path
    ) -> None:
        _init(tmp_path)
        _write_config(tmp_path, token_budget=3000)

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "implement",
                "--query", "add pagination",
                "--project-root", str(tmp_path),
                "--max-tokens", "6000",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        # Silent override is a bug per CLAUDE.md. The advisory must
        # surface both the config value (3000) and the CLI value (6000).
        assert "config token_budget" in (result.stderr or "")
        assert "3000" in (result.stderr or "")
        assert "6000" in (result.stderr or "")

    def test_cli_flag_below_config_no_advisory(self, tmp_path: Path) -> None:
        """When CLI is tighter than config, the user already asked for
        tighter output — no "overridden by" nudge needed."""
        _init(tmp_path)
        _write_config(tmp_path, token_budget=9000)

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "implement",
                "--query", "add pagination",
                "--project-root", str(tmp_path),
                "--max-tokens", "2000",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert "overridden by" not in (result.stderr or "")

    def test_env_var_applies_when_no_cli_flag(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _init(tmp_path)
        _write_config(tmp_path, token_budget=3000)
        monkeypatch.setenv("CONTEXT_ROUTER_TOKEN_BUDGET", "5000")

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "implement",
                "--query", "add pagination",
                "--project-root", str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        # Env var takes effect silently (no override-advisory needed —
        # env var is the operator's explicit global).

    def test_malformed_env_var_warns(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        _init(tmp_path)
        monkeypatch.setenv("CONTEXT_ROUTER_TOKEN_BUDGET", "not-an-int")

        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "implement",
                "--query", "add pagination",
                "--project-root", str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert "CONTEXT_ROUTER_TOKEN_BUDGET" in (result.stderr or "")


# ---------------------------------------------------------------------------
# β2 — review-mode sane defaults
# ---------------------------------------------------------------------------


class TestReviewModeDefaults:
    """Review mode should default to a tight 5-item / 1500-token pack (v4.4)."""

    def test_defaults_apply_when_flags_omitted(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "review",
                "--project-root", str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        # The stderr advisory names both defaults so the user can repro.
        # v4.4: review default tightened from 4000 → 1500 tokens.
        stderr = result.stderr or ""
        assert "review-mode defaults applied" in stderr
        assert "--top-k 5" in stderr
        assert "--max-tokens 1500" in stderr
        # Post-rank cap cannot exceed 5 items regardless of candidate count.
        payload = json.loads(result.stdout)
        assert len(payload["selected_items"]) <= 5

    def test_explicit_top_k_suppresses_default(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "review",
                "--project-root", str(tmp_path),
                "--top-k", "10",
                "--max-tokens", "4000",  # explicit too, so no advisory
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert "review-mode defaults applied" not in (result.stderr or "")

    def test_defaults_do_not_fire_outside_review(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "implement",
                "--query", "add pagination",
                "--project-root", str(tmp_path),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert "review-mode defaults applied" not in (result.stderr or "")


# ---------------------------------------------------------------------------
# β4 — --format agent output
# ---------------------------------------------------------------------------


class TestAgentFormatCLI:
    """``--format agent`` emits a minimal {path, lines, reason} array."""

    def test_agent_format_yields_valid_array(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "implement",
                "--query", "add pagination",
                "--project-root", str(tmp_path),
                "--format", "agent",
            ],
        )
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        for elem in payload:
            assert set(elem.keys()) == {"path", "lines", "reason"}

    def test_agent_format_in_handover_prints_advisory(
        self, tmp_path: Path
    ) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "handover",
                "--project-root", str(tmp_path),
                "--format", "agent",
            ],
        )
        # Format still emits (silent no-op is banned) but a stderr
        # advisory tells the user they probably wanted a different mode.
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        assert "agent format is optimized" in (result.stderr or "")
        json.loads(result.stdout)  # must still be valid JSON

    def test_invalid_format_exits_2(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "pack",
                "--mode", "implement",
                "--query", "x",
                "--project-root", str(tmp_path),
                "--format", "xml",
            ],
        )
        assert result.exit_code == 2
