#!/usr/bin/env python3
"""context-router hook: capture a debug-session observation after a bug is resolved.

Call this after you have identified and fixed a bug to preserve the debug
session in memory.  The error description, fix, and affected files are stored
so future debug packs can surface relevant prior art.

    python scripts/hooks/on_debug_resolve.py \\
        --error-desc "KeyError on missing 'user_id' in session dict" \\
        --fix "added .get() with a default value in session_middleware.py" \\
        --files "middleware/session.py tests/test_session.py" \\
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
        description="Capture a debug observation after resolving a bug.",
    )
    parser.add_argument(
        "--error-desc",
        required=True,
        help="Short description of the error or failure (becomes the summary).",
    )
    parser.add_argument(
        "--fix",
        default="",
        help="Short description of the fix or resolution.",
    )
    parser.add_argument(
        "--files",
        default="",
        help="Space-separated file paths touched during debugging.",
    )
    parser.add_argument("--commit", default="", help="Git commit SHA of the fix if available.")
    parser.add_argument(
        "--project-root",
        default="",
        help="Project root. Auto-detected when omitted.",
    )
    args = parser.parse_args()

    cmd = [
        "uv", "run", "context-router", "memory", "capture",
        args.error_desc,
        "--task-type", "debug",
    ]
    if args.fix:
        cmd += ["--fix", args.fix]
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
