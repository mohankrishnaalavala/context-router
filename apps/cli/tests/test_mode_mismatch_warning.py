"""CLI tests for the ``mode-mismatch-warning`` outcome (v3.2 P1).

Covers:
  * ``--mode review`` + free-text query + clean git tree →
    stderr contains the canonical ``try --mode debug`` nudge.
  * ``--mode review`` + dirty git tree → NO warning (happy path).
  * ``--mode debug`` + query + clean tree → NO warning (debug is
    fine diff-less; only review pretends to want a diff).
  * Non-git directory → stderr contains the skip notice, not the
    main warning (silent-is-a-bug rule).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from cli.main import app
from typer.testing import CliRunner

# Click/Typer >=0.24 separates stdout/stderr by default; use result.stderr.
runner = CliRunner()

_WARN_SUBSTR = "try --mode debug"
_SKIP_SUBSTR = "review-mode diff check skipped"


def _init_project(path: Path) -> None:
    """Create ``.context-router/context-router.db`` so pack has an index."""
    result = runner.invoke(app, ["init", "--project-root", str(path)])
    assert result.exit_code == 0, result.output


def _git_init_committed(path: Path) -> None:
    """Make *path* a git repo with one committed file (clean working tree)."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    # Local identity so `git commit` doesn't fail on CI sandboxes.
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


def test_review_mode_with_query_on_clean_tree_warns_stderr(tmp_path: Path) -> None:
    _git_init_committed(tmp_path)
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "find the bug",
            "--project-root", str(tmp_path),
        ],
    )
    # Exit code may be 0 or non-zero depending on index contents, but the
    # warning is the contract — must be on stderr regardless.
    assert _WARN_SUBSTR in result.stderr, (
        f"expected stderr to contain {_WARN_SUBSTR!r}; got stderr={result.stderr!r}"
    )


def test_review_mode_with_dirty_tree_does_not_warn(tmp_path: Path) -> None:
    _git_init_committed(tmp_path)
    # Dirty the tree — an unstaged change in README.md.
    (tmp_path / "README.md").write_text("hello\nchanged\n")
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "summarise this diff",
            "--project-root", str(tmp_path),
        ],
    )
    assert _WARN_SUBSTR not in result.stderr, (
        f"happy-path review (diff present) must be silent; got stderr={result.stderr!r}"
    )


def test_review_mode_with_staged_diff_does_not_warn(tmp_path: Path) -> None:
    _git_init_committed(tmp_path)
    # Staged-only change: add a new file and `git add` it.
    new_file = tmp_path / "feature.py"
    new_file.write_text("def x():\n    return 1\n")
    subprocess.run(["git", "add", "feature.py"], cwd=tmp_path, check=True)
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "summarise",
            "--project-root", str(tmp_path),
        ],
    )
    assert _WARN_SUBSTR not in result.stderr


def test_debug_mode_on_clean_tree_does_not_warn(tmp_path: Path) -> None:
    _git_init_committed(tmp_path)
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "debug",
            "--query", "why does foo fail",
            "--project-root", str(tmp_path),
        ],
    )
    # Debug mode is the recommended alternative — it must be quiet.
    assert _WARN_SUBSTR not in result.stderr
    # And no skip notice either — only review mode triggers the probe.
    assert _SKIP_SUBSTR not in result.stderr


def test_non_git_directory_emits_skip_notice(tmp_path: Path) -> None:
    # No `git init` here — a bare .context-router init only.
    _init_project(tmp_path)

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "whatever",
            "--project-root", str(tmp_path),
        ],
    )
    # Absence-of-warning must be explained — silent-is-a-bug.
    assert _SKIP_SUBSTR in result.stderr, (
        f"non-git tree must print a skip notice; got stderr={result.stderr!r}"
    )
    # And the main warning must NOT be emitted — we could not verify the
    # working tree, so we cannot claim the user is mis-using review mode.
    assert _WARN_SUBSTR not in result.stderr


def test_review_mode_with_empty_query_does_not_probe(tmp_path: Path) -> None:
    """An empty query in review mode skips the probe entirely.

    Review mode against a PR diff without a query is the canonical "summarise
    this PR" use case — the warning only applies when the user supplied a
    free-text query (meaning they're trying to use review like debug).
    """
    _init_project(tmp_path)  # no git init → would trigger skip notice if probed

    result = runner.invoke(
        app,
        [
            "pack",
            "--mode", "review",
            "--query", "",
            "--project-root", str(tmp_path),
        ],
    )
    assert _WARN_SUBSTR not in result.stderr
    assert _SKIP_SUBSTR not in result.stderr
