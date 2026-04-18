"""Smoke harness: count MCP progress notifications for a large pack.

Drives ``apps/mcp-server/src/mcp_server/main.py`` via a stdio JSON-RPC
session, asks for a ``get_context_pack`` with a ``progressToken``, and
asserts that at least two ``notifications/progress`` frames arrive before
the final ``tools/call`` response.

Prints ``PASS mcp-pack-streams-large (N progress notifications)`` on
success, ``FAIL mcp-pack-streams-large: <reason>`` on failure.  Used by
``scripts/smoke-v3.sh`` under the ``mcp-pack-streams-large`` outcome.

The server threshold is lowered via ``CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS=0``
so this check works against any indexed fixture — we're testing the MCP
plumbing, not the ranker's token counts.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _drain_until(
    proc: subprocess.Popen,
    req_id: int,
    *,
    timeout_s: float = 60.0,
) -> tuple[list[dict], dict | None]:
    """Read JSON-RPC frames until the response for ``req_id`` arrives.

    Returns (notifications, final_response).  If stdout closes early or
    parsing fails, returns whatever was read with final_response=None.
    """
    notes: list[dict] = []
    deadline = time.monotonic() + timeout_s if timeout_s else None

    while True:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return notes, None
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                return notes, None
        line = proc.stdout.readline()
        if not line:
            return notes, None
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue
        if frame.get("id") == req_id:
            return notes, frame
        if frame.get("method", "").startswith("notifications/"):
            notes.append(frame)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("FAIL mcp-pack-streams-large: usage: mcp_progress_count.py <project_root>")
        return 1

    project_root = Path(argv[1]).resolve()
    if not project_root.exists():
        print(f"FAIL mcp-pack-streams-large: project_root not found: {project_root}")
        return 1

    env = os.environ.copy()
    # Force the gate open so any indexed fixture exercises the streaming path.
    env["CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS"] = "0"

    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_server.main"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "1"},
            },
        })
        _, init_resp = _drain_until(proc, 1, timeout_s=15.0)
        if init_resp is None or init_resp.get("error"):
            print(f"FAIL mcp-pack-streams-large: initialize failed: {init_resp}")
            return 1

        _send(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "get_context_pack",
                "arguments": {
                    "mode": "implement",
                    "query": "streaming progress smoke",
                    "project_root": str(project_root),
                    "progressToken": "smoke-large-pack",
                },
            },
        })
        notes, resp = _drain_until(proc, 2, timeout_s=90.0)
        if resp is None:
            print("FAIL mcp-pack-streams-large: no final tools/call response")
            return 1
        if resp.get("result", {}).get("isError", True):
            print(f"FAIL mcp-pack-streams-large: tool reported error: {resp}")
            return 1

        progress_notes = [n for n in notes if n.get("method") == "notifications/progress"]
        # Verify each progress frame references our token — catches leaks.
        for note in progress_notes:
            token = note.get("params", {}).get("progressToken")
            if token != "smoke-large-pack":
                print(f"FAIL mcp-pack-streams-large: wrong progressToken {token!r}")
                return 1

        count = len(progress_notes)
        if count < 2:
            print(f"FAIL mcp-pack-streams-large: expected >=2 progress notifications, got {count}")
            return 1
        print(f"PASS mcp-pack-streams-large ({count} progress notifications)")
        return 0
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
