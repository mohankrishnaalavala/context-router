"""Unit tests for :mod:`graph_index.blame` (v3.2 diff-aware-ranking-boost)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from graph_index.blame import (
    GitDiffUnavailable,
    get_changed_lines,
    parse_unified_diff,
    symbol_overlaps_diff,
)


SAMPLE_DIFF = """\
diff --git a/pkg/mod.py b/pkg/mod.py
index 1111111..2222222 100644
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -10,0 +11,3 @@
+added line 11
+added line 12
+added line 13
@@ -40,2 +43 @@
-removed a
-removed b
+survivor
diff --git a/pkg/other.py b/pkg/other.py
index 3333333..4444444 100644
--- a/pkg/other.py
+++ b/pkg/other.py
@@ -5 +5 @@
-old
+new
"""


def test_parse_unified_diff_extracts_new_side_lines() -> None:
    """Hunks map ``@@ -a,b +c,d @@`` to new-side lines ``c..c+d-1``."""
    parsed = parse_unified_diff(SAMPLE_DIFF)
    assert set(parsed.keys()) == {"pkg/mod.py", "pkg/other.py"}
    # First hunk: +11,3 → lines 11, 12, 13
    # Second hunk: +43 (count omitted → 1) → line 43
    assert parsed["pkg/mod.py"] == {11, 12, 13, 43}
    # Single-line replacement: +5 → line 5
    assert parsed["pkg/other.py"] == {5}


def test_parse_unified_diff_pure_deletion_records_anchor() -> None:
    """A pure deletion (``+c,0``) records the new-side anchor line.

    A delete-before-line-7 still touches the symbol that owns line 7
    (e.g. its docstring), so the boost should fire.
    """
    pure_delete = (
        "diff --git a/a.py b/a.py\n"
        "--- a/a.py\n"
        "+++ b/a.py\n"
        "@@ -20,3 +19,0 @@\n"
        "-del 1\n"
        "-del 2\n"
        "-del 3\n"
    )
    parsed = parse_unified_diff(pure_delete)
    assert parsed == {"a.py": {19}}


def test_parse_unified_diff_empty_input_returns_empty_map() -> None:
    """No hunks → empty dict, not an error."""
    assert parse_unified_diff("") == {}
    assert parse_unified_diff("no diff here\n") == {}


def test_parse_unified_diff_rename_without_hunks_still_listed() -> None:
    """A rename-only diff lists the new path with an empty set.

    Keeps the caller's overlap check deterministic — the file is "known
    changed", just with zero lines that overlap any symbol range.
    """
    rename_only = (
        "diff --git a/old.py b/new.py\n"
        "similarity index 100%\n"
        "rename from old.py\n"
        "rename to new.py\n"
    )
    parsed = parse_unified_diff(rename_only)
    assert parsed == {"new.py": set()}


# ---------------------------------------------------------------------------
# symbol_overlaps_diff
# ---------------------------------------------------------------------------


def test_symbol_overlaps_diff_full_overlap() -> None:
    """Symbol range fully contained in diff set → True."""
    assert symbol_overlaps_diff(10, 12, {10, 11, 12}) is True


def test_symbol_overlaps_diff_partial_overlap() -> None:
    """Diff touches a single line inside the symbol range → True."""
    assert symbol_overlaps_diff(60, 150, {70, 71, 72}) is True


def test_symbol_overlaps_diff_boundary_inclusive() -> None:
    """Both endpoints are inclusive (diff at end-line still counts)."""
    assert symbol_overlaps_diff(60, 150, {150}) is True
    assert symbol_overlaps_diff(60, 150, {60}) is True


def test_symbol_overlaps_diff_no_overlap() -> None:
    """Disjoint ranges → False (both sides)."""
    assert symbol_overlaps_diff(10, 20, {5, 6, 7}) is False
    assert symbol_overlaps_diff(10, 20, {21, 22}) is False


def test_symbol_overlaps_diff_empty_changed_lines_is_false() -> None:
    """Negative case: empty diff set never overlaps anything."""
    assert symbol_overlaps_diff(1, 1000, set()) is False


def test_symbol_overlaps_diff_single_line_symbol() -> None:
    """Single-line symbol (start == end) overlaps iff that line changed."""
    assert symbol_overlaps_diff(42, 42, {42}) is True
    assert symbol_overlaps_diff(42, 42, {41, 43}) is False


def test_symbol_overlaps_diff_invalid_range_returns_false() -> None:
    """Unusable symbol line data must NOT trigger a spurious boost."""
    assert symbol_overlaps_diff(0, 0, {0, 1, 2}) is False
    assert symbol_overlaps_diff(-5, 10, {1, 2}) is False
    # end < start → False
    assert symbol_overlaps_diff(20, 10, {15}) is False


# ---------------------------------------------------------------------------
# get_changed_lines (filesystem integration)
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> None:
    """Run a git command inside *cwd*, capturing output for test stability."""
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "t@t.t", cwd=root)
    _git("config", "user.name", "T", cwd=root)
    _git("config", "commit.gpgsign", "false", cwd=root)


def test_get_changed_lines_non_repo_returns_empty(tmp_path: Path) -> None:
    """Silent-failure contract: no git repo → empty dict, never raises."""
    assert get_changed_lines(tmp_path, "HEAD") == {}


def test_get_changed_lines_empty_spec_returns_empty(tmp_path: Path) -> None:
    """Empty diff_spec short-circuits before any subprocess call."""
    assert get_changed_lines(tmp_path, "") == {}


def test_get_changed_lines_head_reads_working_tree(tmp_path: Path) -> None:
    """Working-tree modification against HEAD is surfaced by spec="HEAD"."""
    _init_repo(tmp_path)
    target = tmp_path / "app.py"
    target.write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    _git("add", "app.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "init", cwd=tmp_path)

    # Modify the second function; the hunk will reference its new-side line.
    target.write_text("def a():\n    return 1\n\ndef b():\n    return 99\n")
    changed = get_changed_lines(tmp_path, "HEAD")

    assert set(changed.keys()) == {"app.py"}
    # Some line in the function b() range (lines 4-5) must appear.
    assert changed["app.py"] & {4, 5}


def test_get_changed_lines_commit_sha_diffs_against_parent(tmp_path: Path) -> None:
    """diff_spec=<sha> → ``<sha>^..<sha>`` (commit vs its parent)."""
    _init_repo(tmp_path)
    target = tmp_path / "app.py"
    target.write_text("line1\nline2\nline3\n")
    _git("add", "app.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "first", cwd=tmp_path)

    target.write_text("line1\nchanged\nline3\n")
    _git("add", "app.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "second", cwd=tmp_path)

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    changed = get_changed_lines(tmp_path, sha)
    assert "app.py" in changed
    assert 2 in changed["app.py"]


def test_get_changed_lines_invalid_sha_returns_empty(tmp_path: Path) -> None:
    """Invalid SHA → silent empty return (caller emits the warning)."""
    _init_repo(tmp_path)
    (tmp_path / "x.py").write_text("x = 1\n")
    _git("add", "x.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "init", cwd=tmp_path)

    assert get_changed_lines(tmp_path, "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef") == {}


def test_git_diff_unavailable_raised_on_internal_helper(tmp_path: Path) -> None:
    """The internal runner raises so tests can assert the silent-failure path.

    ``get_changed_lines`` swallows this and returns {} — we exercise the
    raising helper to keep the contract visible to future maintainers.
    """
    from graph_index.blame import _run_git_diff

    with pytest.raises(GitDiffUnavailable):
        _run_git_diff(tmp_path, "HEAD")
