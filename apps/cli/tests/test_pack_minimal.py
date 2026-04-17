"""CLI tests for `context-router pack --mode minimal` (Phase 3 — CRG parity).

Covers:
  * happy path returns JSON with at most 5 items
  * ``--max-tokens`` tightens the ranker's budget for minimal mode
  * empty ``--query`` on minimal mode exits with code 2 (silent-failure rule)
  * other modes are unaffected (smoke check)
"""

from __future__ import annotations

import json
from pathlib import Path

from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def _init(tmp_path: Path) -> None:
    """Initialize a context-router project under *tmp_path*."""
    result = runner.invoke(app, ["init", "--project-root", str(tmp_path)])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_minimal_mode_json_returns_at_most_5_items(tmp_path: Path) -> None:
    _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "minimal",
            "--query", "review the ranker",
            "--project-root", str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "minimal"
    # Back-compat alias mirrors ``selected_items`` as ``items`` for jq recipes
    # in docs/release/v3-outcomes.yaml.
    assert isinstance(payload.get("items"), list)
    assert len(payload["items"]) <= 5
    assert len(payload["selected_items"]) <= 5
    # Minimal mode always carries a next-tool suggestion under metadata.
    assert payload["metadata"].get("next_tool_suggestion")


def test_minimal_mode_max_tokens_flag_tightens_budget(tmp_path: Path) -> None:
    _init(tmp_path)
    loose = runner.invoke(
        app,
        [
            "pack",
            "--mode", "minimal",
            "--query", "find symbols",
            "--project-root", str(tmp_path),
            "--max-tokens", "2000",
            "--json",
        ],
    )
    tight = runner.invoke(
        app,
        [
            "pack",
            "--mode", "minimal",
            "--query", "find symbols",
            "--project-root", str(tmp_path),
            "--max-tokens", "50",
            "--json",
        ],
    )
    assert loose.exit_code == 0, loose.output
    assert tight.exit_code == 0, tight.output
    loose_payload = json.loads(loose.output)
    tight_payload = json.loads(tight.output)
    # Tight pack cannot exceed loose pack's token total; minimal cap still
    # applies to both.
    assert tight_payload["total_est_tokens"] <= max(
        loose_payload["total_est_tokens"], 50
    )
    assert len(tight_payload["selected_items"]) <= 5


# ---------------------------------------------------------------------------
# Silent-failure guard
# ---------------------------------------------------------------------------

def test_minimal_mode_empty_query_exits_2(tmp_path: Path) -> None:
    _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "minimal",
            "--project-root", str(tmp_path),
        ],
    )
    assert result.exit_code == 2
    # Friendly guidance on stderr — not a silent no-op.
    assert "query" in result.output.lower()


def test_minimal_mode_whitespace_only_query_exits_2(tmp_path: Path) -> None:
    _init(tmp_path)
    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "minimal",
            "--query", "   ",
            "--project-root", str(tmp_path),
        ],
    )
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Regression: other modes still succeed with no --max-tokens
# ---------------------------------------------------------------------------

def test_implement_mode_still_works(tmp_path: Path) -> None:
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
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["mode"] == "implement"
    # Implement mode never sets the minimal-only next_tool_suggestion.
    assert "next_tool_suggestion" not in payload.get("metadata", {})
