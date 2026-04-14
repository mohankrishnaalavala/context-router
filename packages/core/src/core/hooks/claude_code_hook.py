#!/usr/bin/env python3
"""Claude Code PostToolUse hook: auto-captures file edits as memory observations.

Installed by ``context-router setup --with-hooks`` to ``.claude/hooks/``.
Claude Code calls this after every Edit/Write/MultiEdit tool use, passing a
JSON payload on stdin.

Hook payload shape (Claude Code PostToolUse):
    {
        "event": "PostToolUse",
        "tool_name": "Edit" | "Write" | "MultiEdit",
        "tool_input": {"file_path": "..."},
        "tool_result": {...}
    }

Usage (direct test):
    echo '{"event":"PostToolUse","tool_name":"Edit","tool_input":{"file_path":"foo.py"}}' \\
         | python3 claude_code_hook.py
"""

from __future__ import annotations

import json
import subprocess
import sys


# Tools that indicate meaningful file edits worth capturing
_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})


def main() -> None:
    """Read the hook payload from stdin and capture an observation if relevant."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return

        payload = json.loads(raw)
        event = payload.get("event", "")
        tool_name = payload.get("tool_name", "")

        if event != "PostToolUse" or tool_name not in _EDIT_TOOLS:
            return

        tool_input = payload.get("tool_input") or {}
        file_path = tool_input.get("file_path", "")
        if not file_path:
            return

        summary = f"Agent edited {file_path} via {tool_name}"
        cmd = [
            "context-router",
            "memory",
            "capture",
            summary,
            "--task-type",
            "implement",
            "--files",
            file_path,
        ]

        subprocess.run(cmd, check=False, capture_output=True)

    except Exception:  # noqa: BLE001
        pass  # never raise — hook errors must not interrupt the agent


if __name__ == "__main__":
    main()
