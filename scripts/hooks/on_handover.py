#!/usr/bin/env python3
"""context-router hook: capture a session-checkpoint observation on handover.

Call this when an agent hands over work to another session or to a human.
The observation is stored so the next session can retrieve it via
'context-router memory search' or the 'get_context_pack --mode handover' pack.

    python scripts/hooks/on_handover.py \\
        --summary "Completed pagination feature for /users endpoint" \\
        --files "api/users.py tests/test_users.py" \\
        --commit abc1234

Exit codes:
  0 — observation captured or duplicate skipped
  1 — error
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture a handover checkpoint observation.",
    )
    parser.add_argument(
        "summary",
        help="One-line summary of what was accomplished in this session.",
    )
    parser.add_argument(
        "--files",
        default="",
        help="Space-separated file paths touched during the session.",
    )
    parser.add_argument("--commit", default="", help="Git commit SHA if available.")
    parser.add_argument(
        "--project-root",
        default="",
        help="Project root. Auto-detected when omitted.",
    )
    args = parser.parse_args()

    cmd = [
        "uv", "run", "context-router", "memory", "capture",
        args.summary,
        "--task-type", "handover",
    ]
    if args.files:
        cmd += ["--files", args.files]
    if args.commit:
        cmd += ["--commit", args.commit]
    if args.project_root:
        cmd += ["--project-root", args.project_root]

    result = subprocess.run(cmd, check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
