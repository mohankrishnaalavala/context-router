"""CLI tests for the ``pre-fix-review-mode`` outcome (v3.2 P2).

Covers:
  * Invalid SHA → clean stderr "commit <sha> not found in ..." and exit 1
    (no traceback). This is the outcome's negative_case.
  * ``--pre-fix`` with ``--mode debug`` (or any non-review mode) → exit 2
    with the "--pre-fix is only valid with --mode review" message.
  * Happy path: ``--pre-fix <sha> --mode review`` routes the commit-range
    diff into the candidate builder. Exercised end-to-end on a tiny tmp
    git repo so we don't depend on the external fastapi fixture.
  * No ``--pre-fix`` on review mode → behaviour unchanged (working-tree
    diff path still runs, no new errors introduced).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def _init_project(path: Path) -> None:
    """Create ``.context-router/context-router.db`` so pack has an index."""
    result = runner.invoke(app, ["init", "--project-root", str(path)])
    assert result.exit_code == 0, result.output


def _git_init_with_commit(path: Path, filename: str = "feature.py") -> str:
    """Init git, create a file, commit it, return the commit SHA.

    The commit has a parent (initial commit) so ``<sha>^..<sha>`` is valid.
    """
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "smoke@example.com"], cwd=path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "smoke"], cwd=path, check=True
    )
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=path, check=True
    )
    # Second commit — this is the SHA we'll use for --pre-fix.
    (path / filename).write_text("def x():\n    return 1\n")
    subprocess.run(["git", "add", filename], cwd=path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add feature"], cwd=path, check=True
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_invalid_sha_emits_clean_error_no_traceback(tmp_path: Path) -> None:
    """Unknown SHA → stderr contains "not found", exit 1, no traceback."""
    _git_init_with_commit(tmp_path)
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--pre-fix", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            "--project-root", str(tmp_path),
        ],
    )
    assert result.exit_code == 1, result.output
    assert "not found" in result.stderr.lower(), (
        f"expected 'not found' on stderr; got stderr={result.stderr!r}"
    )
    # Silent-is-a-bug: no traceback rendering, just the one-line error.
    assert "Traceback" not in result.stderr
    assert "Traceback" not in result.output


def test_pre_fix_with_debug_mode_is_rejected(tmp_path: Path) -> None:
    """--pre-fix combined with a non-review mode → exit 2, clear message."""
    _git_init_with_commit(tmp_path)
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "debug",
            "--pre-fix", "abc1234",
            "--project-root", str(tmp_path),
            "--query", "why fails",
        ],
    )
    assert result.exit_code == 2, result.output
    assert "--pre-fix is only valid with --mode review" in result.stderr


def test_pre_fix_with_implement_mode_is_rejected(tmp_path: Path) -> None:
    """Implement mode + --pre-fix → same rejection (not review-only)."""
    _git_init_with_commit(tmp_path)
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "implement",
            "--pre-fix", "abc1234",
            "--project-root", str(tmp_path),
            "--query", "add foo",
        ],
    )
    assert result.exit_code == 2
    assert "--pre-fix is only valid with --mode review" in result.stderr


def test_pre_fix_with_valid_sha_builds_pack(tmp_path: Path) -> None:
    """Happy path: real SHA + review mode → pack built from commit-range diff.

    We don't assert specific item content (tmp repo has no indexed symbols
    beyond the default) — we assert exit 0 and that no clean-tree warning
    leaks through. The mode-mismatch warning is specifically suppressed
    when --pre-fix is set because the diff source is the commit, not the
    working tree.
    """
    sha = _git_init_with_commit(tmp_path)
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--pre-fix", sha,
            "--project-root", str(tmp_path),
            "--query", "find the bug",
        ],
    )
    assert result.exit_code == 0, (
        f"exit={result.exit_code}, stderr={result.stderr!r}, stdout={result.stdout!r}"
    )
    # Mode-mismatch nudge must NOT fire when --pre-fix is explicit.
    assert "try --mode debug" not in result.stderr


def test_review_without_pre_fix_still_works(tmp_path: Path) -> None:
    """Existing diff-based review flow is not regressed by the new option.

    With a dirty working tree (no --pre-fix), review mode runs normally.
    """
    _git_init_with_commit(tmp_path)
    # Dirty the tree so the mode-mismatch warning is silent (happy path).
    (tmp_path / "README.md").write_text("hello\nchanged\n")
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--project-root", str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "try --mode debug" not in result.stderr


def test_orchestrator_rejects_unknown_sha_programmatically(tmp_path: Path) -> None:
    """Direct orchestrator call with unknown SHA raises ValueError.

    CLI wraps this into a clean exit-1 message; this test covers the
    contract surface used by the MCP tool (which returns it as a
    ``{"error": ...}`` response).
    """
    import pytest
    from core.orchestrator import Orchestrator

    _git_init_with_commit(tmp_path)
    _init_project(tmp_path)

    orch = Orchestrator(project_root=tmp_path)
    with pytest.raises(ValueError, match="not found"):
        orch.build_pack("review", "", pre_fix="deadbeefffffffffffffffffffffffffffffffff")


def test_orchestrator_ignores_pre_fix_for_non_review_mode(tmp_path: Path) -> None:
    """Orchestrator-level: non-review mode treats pre_fix as inert.

    The CLI rejects the combination at the typer boundary (exit 2), but
    the orchestrator itself accepts the kwarg without validating the SHA
    for non-review modes — so callers that forget to pre-check can't
    accidentally trip the validator.
    """
    from core.orchestrator import Orchestrator

    sha = _git_init_with_commit(tmp_path)
    _init_project(tmp_path)

    orch = Orchestrator(project_root=tmp_path)
    # Should NOT raise — debug mode ignores pre_fix entirely.
    pack = orch.build_pack("debug", "foo", pre_fix=sha)
    assert pack.mode == "debug"


def test_mcp_tool_rejects_pre_fix_outside_review_mode(tmp_path: Path) -> None:
    """MCP ``get_context_pack`` returns a clean error dict for the combo."""
    from mcp_server.tools import get_context_pack

    _git_init_with_commit(tmp_path)
    _init_project(tmp_path)

    result = get_context_pack(
        mode="debug",
        query="find bug",
        project_root=str(tmp_path),
        pre_fix="abc1234",
    )
    assert "error" in result
    assert "review" in result["error"].lower()


def test_mcp_tool_returns_error_for_unknown_sha(tmp_path: Path) -> None:
    """MCP tool propagates orchestrator ValueError as ``{"error": ...}``."""
    from mcp_server.tools import get_context_pack

    _git_init_with_commit(tmp_path)
    _init_project(tmp_path)

    result = get_context_pack(
        mode="review",
        query="",
        project_root=str(tmp_path),
        pre_fix="deadbeefffffffffffffffffffffffffffffffff",
    )
    assert "error" in result
    assert "not found" in result["error"].lower()
