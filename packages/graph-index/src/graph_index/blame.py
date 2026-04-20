"""Diff-aware blame helpers for the v3.2 ``diff-aware-ranking-boost`` outcome.

When a diff is present (either the working-tree diff against ``HEAD`` or a
named commit SHA), the ranker should lift items whose underlying symbol
actually overlaps the CHANGED lines — not just the changed FILES. This
module owns the "which lines in which files changed" lookup so the ranker
stays stateless with respect to git.

The parser consumes ``git diff --unified=0 <spec>`` output and extracts the
new-side line numbers from each hunk header of the form
``@@ -a,b +c,d @@`` into a per-file ``set[int]`` of affected line numbers.

Silent-failure policy (CLAUDE.md):
    This module never writes to stderr. When the underlying git command
    fails (not a repo, invalid SHA, missing git binary), we return an
    empty ``{}`` and let the CALLER emit a single warning that names the
    reason — the ranker owns user-visible diagnostics, not this module.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# ``@@ -a[,b] +c[,d] @@`` — the comma-count is optional per the unified-diff
# spec (single-line hunks omit it). We only consume the new-side range.
_HUNK_RE = re.compile(
    r"^@@\s+-\d+(?:,\d+)?\s+\+(?P<start>\d+)(?:,(?P<count>\d+))?\s+@@"
)

# ``diff --git a/old b/new`` — the new-side path is authoritative for line
# numbers. For renames with no content change git emits a ``diff --git``
# line but no ``+++`` header, so we fall back to the ``b/`` component.
_DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<old>.+?) b/(?P<new>.+)$")
_PLUS_FILE_RE = re.compile(r"^\+\+\+ b/(?P<path>.+)$")


class GitDiffUnavailable(RuntimeError):
    """Raised when ``git diff`` cannot produce output for *spec*.

    Callers catch this and emit a single stderr warning describing the
    reason (silent-failure rule).
    """


def parse_unified_diff(diff_text: str) -> dict[str, set[int]]:
    """Parse unified-diff text into ``{new_path: {changed_line, ...}}``.

    Only the new-side line numbers are tracked — a deleted region has no
    new-side lines and therefore contributes nothing to the overlap set
    (diff-aware boost targets survived lines that moved or got edited).

    For a header of the form ``@@ -a,b +c,d @@`` the affected new-side
    line range is ``c .. c + max(1, d) - 1`` (``d = 0`` means a deletion
    anchored before line ``c``; we still record ``c`` so a deletion at a
    symbol's top line is treated as a change to it).

    Args:
        diff_text: Output of ``git diff --unified=0 <spec>``.

    Returns:
        Mapping from new-side path (repo-relative, posix-style) to the
        set of changed line numbers. Returns an empty dict when *diff_text*
        contains no hunks.
    """
    by_path: dict[str, set[int]] = {}
    current_path: str | None = None

    for line in diff_text.splitlines():
        m_diff = _DIFF_GIT_RE.match(line)
        if m_diff is not None:
            current_path = m_diff.group("new")
            # Pre-seed an empty set so pure-rename diffs (no hunks) still
            # appear in the output even though they contribute 0 lines.
            by_path.setdefault(current_path, set())
            continue
        m_plus = _PLUS_FILE_RE.match(line)
        if m_plus is not None:
            current_path = m_plus.group("path")
            by_path.setdefault(current_path, set())
            continue
        m_hunk = _HUNK_RE.match(line)
        if m_hunk is None or current_path is None:
            continue
        start = int(m_hunk.group("start"))
        count_raw = m_hunk.group("count")
        count = int(count_raw) if count_raw is not None else 1
        if count <= 0:
            # Deletion anchored at new-side position *start* with no added
            # lines. Record *start* so a delete-at-boundary still counts
            # as touching the symbol that owns line *start*.
            by_path[current_path].add(start)
            continue
        by_path[current_path].update(range(start, start + count))

    return by_path


def _run_git_diff(project_root: Path, diff_spec: str) -> str:
    """Run ``git diff --unified=0`` for *diff_spec* and return stdout.

    Raises:
        GitDiffUnavailable: when the command fails OR git is unavailable.
    """
    if diff_spec == "HEAD":
        # Working-tree diff (staged + unstaged) against HEAD — matches the
        # review-mode contract of "what's pending right now".
        args = ["git", "diff", "--unified=0", "HEAD"]
    else:
        # Diff a specific commit against its parent, e.g. ``fa3588c^..fa3588c``.
        # Mirrors ``_pre_fix_range`` in the orchestrator.
        sha = diff_spec.strip()
        args = ["git", "diff", "--unified=0", f"{sha}^..{sha}"]
    try:
        result = subprocess.run(
            args,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        raise GitDiffUnavailable(f"git not available: {exc}") from exc
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip() or f"rc={result.returncode}"
        raise GitDiffUnavailable(msg)
    return result.stdout


def get_changed_lines(
    project_root: Path,
    diff_spec: str,
) -> dict[str, set[int]]:
    """Return ``{relative_path: {changed_line, ...}}`` for *diff_spec*.

    Args:
        project_root: Working directory for ``git diff``. Must be a
            repository root (or anywhere inside the working tree).
        diff_spec: Either ``"HEAD"`` (staged + unstaged vs ``HEAD``) or a
            commit SHA (diffed against its parent via ``<sha>^..<sha>``).

    Returns:
        Mapping of new-side repo-relative paths (posix-style) to the set
        of affected new-side line numbers. Empty dict when:

        * the diff is empty (no changes against *diff_spec*),
        * *project_root* isn't inside a git working tree,
        * ``git`` is missing / the SHA doesn't resolve.

    Silent-failure policy: this function never prints. The caller owns
    the stderr warning so the message can name the context (``diff-aware
    boost skipped: <reason>``) that the ranker knows but this module
    doesn't.
    """
    if not diff_spec:
        return {}
    try:
        diff_text = _run_git_diff(project_root, diff_spec)
    except GitDiffUnavailable:
        return {}
    if not diff_text:
        return {}
    return parse_unified_diff(diff_text)


def symbol_overlaps_diff(
    symbol_start: int,
    symbol_end: int,
    changed_lines: set[int],
) -> bool:
    """Return True iff ``[symbol_start, symbol_end]`` intersects *changed_lines*.

    Treats both endpoints as inclusive — a symbol spanning lines 60..150
    with a diff touching line 150 counts as overlap.

    Edge cases:
        * ``changed_lines`` empty → False.
        * Invalid range (``symbol_end < symbol_start`` or non-positive
          endpoints) → False. Callers with unusable line data should
          not see a spurious boost.
    """
    if not changed_lines:
        return False
    if symbol_start <= 0 or symbol_end <= 0:
        return False
    if symbol_end < symbol_start:
        return False
    # Short-circuit on the smaller side — most diffs touch a handful of
    # lines, most symbols span tens, so probing ``changed_lines`` directly
    # is cheaper than building an intermediate range().
    if len(changed_lines) <= (symbol_end - symbol_start + 1):
        for ln in changed_lines:
            if symbol_start <= ln <= symbol_end:
                return True
        return False
    for ln in range(symbol_start, symbol_end + 1):
        if ln in changed_lines:
            return True
    return False
