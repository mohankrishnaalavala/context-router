"""Git diff parser for context-router graph indexing.

Parses the output of `git diff --name-status` (and optionally hunk headers
from `git diff`) to produce a list of ChangedFile objects used for
incremental indexing.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ChangedFile:
    """Represents a single file change from a git diff."""

    path: Path
    status: str  # "added" | "modified" | "deleted" | "renamed" | "unknown"
    hunks: list[str] = field(default_factory=list)
    old_path: Path | None = None


class GitDiffParser:
    """Parses git diff --name-status output into ChangedFile objects."""

    # Status letter → canonical status string
    _STATUS_MAP = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "type-changed",
        "U": "unmerged",
    }

    def parse(self, diff_text: str) -> list[ChangedFile]:
        """Parse the output of `git diff --name-status` into ChangedFile objects.

        Accepts tab-separated lines of the form:
          M\tpath/to/file.py
          R100\told/path.py\tnew/path.py
          A\tpath/to/new.py
          D\tpath/to/removed.py

        Args:
            diff_text: String output from `git diff --name-status`.

        Returns:
            List of ChangedFile objects, one per changed file.
        """
        changed: list[ChangedFile] = []

        for line in diff_text.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = line.split("\t")
            if len(parts) < 2:
                continue

            status_code = parts[0][0].upper()  # "M", "A", "D", "R100" → "R"
            status = self._STATUS_MAP.get(status_code, "unknown")

            if status == "renamed" and len(parts) >= 3:
                old_path = Path(parts[1])
                new_path = Path(parts[2])
                changed.append(
                    ChangedFile(path=new_path, status=status, old_path=old_path)
                )
            else:
                changed.append(ChangedFile(path=Path(parts[1]), status=status))

        return changed

    @staticmethod
    def from_git(root: Path, since: str) -> list[ChangedFile]:
        """Run `git diff --name-status <since>` and parse the output.

        Args:
            root: Repository root directory.
            since: Git ref to diff against (e.g. "HEAD~1", "main").

        Returns:
            List of ChangedFile objects.

        Raises:
            RuntimeError: If the git command fails.
        """
        result = subprocess.run(
            ["git", "diff", "--name-status", since],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git diff failed: {result.stderr.strip()}"
            )
        return GitDiffParser().parse(result.stdout)
