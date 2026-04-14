#!/usr/bin/env python3
"""Post-commit hook: auto-captures commit message + changed files as a memory observation.

Installed by ``context-router setup --with-hooks`` to ``.git/hooks/post-commit``.
Runs silently after every commit — errors are swallowed so they never block a commit.

Usage (direct):
    python3 post_commit.py
"""

from __future__ import annotations

import subprocess
import sys


def main() -> None:
    """Capture the latest commit as a context-router memory observation."""
    try:
        # Get the commit subject line
        msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"], text=True
        ).strip()

        # Get files changed in this commit
        files_output = subprocess.check_output(
            ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", "HEAD"],
            text=True,
        ).strip()
        file_list = [f for f in files_output.splitlines() if f]

        summary = f"Committed: {msg}"

        # Build the memory capture command
        cmd = [
            "context-router",
            "memory",
            "capture",
            summary,
            "--task-type",
            "implement",
        ]
        for f in file_list[:10]:  # cap at 10 files to keep the observation focused
            cmd += ["--files", f]

        # Run non-blocking — a failure here must never fail the git commit
        subprocess.run(cmd, check=False, capture_output=True)

    except Exception:  # noqa: BLE001
        pass  # silent — hooks should never break the git workflow


if __name__ == "__main__":
    main()
