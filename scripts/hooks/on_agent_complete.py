#!/usr/bin/env python3
"""context-router hook: capture a memory observation after an agent completes a task.

Adapter-callable entry point.  Invoke after your agent finishes a task to
persist a normalized observation:

    python scripts/hooks/on_agent_complete.py \\
        --summary "Implemented pagination for /users endpoint" \\
        --task-type implement \\
        --files "api/users.py tests/test_users.py" \\
        --commit abc1234 \\
        --fix "added cursor-based pagination with limit/offset params"

Exit codes:
  0 — observation captured or duplicate skipped
  1 — missing required argument or database error
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a task observation after agent completion.",
    )
    parser.add_argument("summary", help="One-line task summary (required).")
    parser.add_argument(
        "--task-type",
        default="general",
        help="Task category: implement, debug, review, refactor, commit, general.",
    )
    parser.add_argument(
        "--files",
        default="",
        help="Space-separated file paths touched during the task.",
    )
    parser.add_argument("--commit", default="", help="Git commit SHA if available.")
    parser.add_argument(
        "--fix",
        default="",
        help="Short description of the fix or resolution.",
    )
    parser.add_argument(
        "--project-root",
        default="",
        help="Project root. Auto-detected when omitted.",
    )
    args = parser.parse_args()

    cmd = [
        "uv", "run", "context-router", "memory", "capture",
        args.summary,
        "--task-type", args.task_type,
    ]
    if args.files:
        cmd += ["--files", args.files]
    if args.commit:
        cmd += ["--commit", args.commit]
    if args.fix:
        cmd += ["--fix", args.fix]
    if args.project_root:
        cmd += ["--project-root", args.project_root]

    result = subprocess.run(cmd, check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
