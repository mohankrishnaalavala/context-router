"""Smoke harness for the ``mcp-progress-notifications`` outcome (v3.3.0 γ1).

Verifies three things end-to-end against a live MCP server subprocess:

1. ``initialize`` response advertises ``capabilities.progress == true`` so
   clients know they can pass ``progressToken`` on ``tools/call``.
2. ``get_context_pack`` with a ``progressToken`` receives ≥ 1
   ``notifications/progress`` frame (carrying that token) before the final
   ``tools/call`` response, for a pack whose ``total_est_tokens`` ≥ 2000.
3. The negative case — a pack below the streaming threshold emits zero
   progress frames — is exercised by the dedicated pytest in
   ``apps/mcp-server/tests/test_progress.py`` and is not re-asserted here
   to keep the smoke runtime short.

Prints ``PASS mcp-progress-notifications (<N> frames)`` on success and
``FAIL mcp-progress-notifications: <reason>`` on failure.

Design note:
    The existing ``mcp_progress_count.py`` harness runs with
    ``CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS=0`` to force the gate open
    regardless of pack size.  This probe instead leaves the default
    threshold in place and uses this repo's own tree — which ranks
    comfortably past 2 000 tokens for common queries — so the check
    exercises the *production* streaming path.  If the ranker ever shrinks
    pack sizes below the threshold, this probe will flip to FAIL loudly
    rather than silently passing on the overridden gate.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path


_SERVER_CMD = [sys.executable, "-m", "mcp_server.main"]


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _drain_until(
    proc: subprocess.Popen,
    req_id: int,
    *,
    timeout_s: float = 60.0,
) -> tuple[list[dict], dict | None]:
    notes: list[dict] = []
    deadline = time.monotonic() + timeout_s
    while True:
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


def _run(project_root: Path) -> tuple[bool, str]:
    env = os.environ.copy()
    # Keep the *default* streaming threshold so the probe truly tests the
    # production gate — see module docstring.
    env.pop("CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS", None)

    proc = subprocess.Popen(
        _SERVER_CMD,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=env,
    )
    try:
        # 1. initialize — assert progress capability advertised
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-progress-v3-3", "version": "1"},
            },
        })
        _, init = _drain_until(proc, 1, timeout_s=15.0)
        if init is None or init.get("error"):
            return False, f"initialize failed: {init!r}"
        caps = init.get("result", {}).get("capabilities", {})
        if caps.get("progress") is not True:
            return False, f"capabilities.progress must be True; got {caps!r}"

        # 2. tools/call get_context_pack with progressToken
        token = "smoke-v3-3-progress"
        _send(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {
                "name": "get_context_pack",
                "arguments": {
                    "mode": "implement",
                    "query": "orchestrator build pack ranking",
                    "project_root": str(project_root),
                    "progressToken": token,
                },
            },
        })
        notes, resp = _drain_until(proc, 2, timeout_s=90.0)
        if resp is None:
            return False, "no final tools/call response"
        if resp.get("result", {}).get("isError", True):
            return False, f"tool reported error: {resp!r}"

        # 3. Inspect the pack's declared token count — the threshold test
        # only meaningfully passes when the pack is large enough to trip
        # the default gate (≥ 2000 tokens).  A pack smaller than that is a
        # ranker regression, not an MCP bug; surface it as a distinct
        # FAIL reason so the operator knows which layer to debug.
        try:
            content = resp["result"]["content"][0]["text"]
            pack = json.loads(content)
            total_tokens = int(pack.get("total_est_tokens", 0))
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
            return False, f"could not parse pack from response: {exc}"

        if total_tokens < 2000:
            return False, (
                f"pack was only {total_tokens} tokens — below the 2000-token "
                "streaming threshold, so no progress notifications were "
                "expected; indexer or ranker likely regressed. Try a "
                "larger fixture project_root."
            )

        progress = [n for n in notes if n.get("method") == "notifications/progress"]
        if not progress:
            return False, (
                f"expected ≥ 1 notifications/progress for a {total_tokens}-token "
                f"pack, got none (notes={[n.get('method') for n in notes]!r})"
            )
        for note in progress:
            got_token = note.get("params", {}).get("progressToken")
            if got_token != token:
                return False, f"progress frame carried wrong token: {got_token!r}"

        return True, f"{len(progress)} frame(s) for a {total_tokens}-token pack"
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("FAIL mcp-progress-notifications: usage: mcp_progress_notifications_probe.py <project_root>")
        return 1
    project_root = Path(argv[1]).resolve()
    if not project_root.exists():
        print(f"FAIL mcp-progress-notifications: project_root not found: {project_root}")
        return 1
    ok, msg = _run(project_root)
    if ok:
        print(f"PASS mcp-progress-notifications ({msg})")
        return 0
    print(f"FAIL mcp-progress-notifications: {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
