"""Smoke harness: verify tools/call content blocks carry mimeType.

Drives ``apps/mcp-server/src/mcp_server/main.py`` via a stdio JSON-RPC
session, performs ``initialize`` then ``tools/call`` for a cheap tool
(``build_index`` against a scratch dir — it returns an error dict which
is still a fully-formed content block), and asserts the returned
``content[0].mimeType`` is one of the accepted MIME types.

Prints ``PASS mcp-mimetype-content (mimeType=<value>)`` on success,
``FAIL mcp-mimetype-content: <reason>`` on failure.  Used by
``scripts/smoke-v3.sh`` under the ``mcp-mimetype-content`` outcome.
"""

from __future__ import annotations

import json
import select
import subprocess
import sys
import tempfile
import time


_ACCEPTED_MIMES = {"application/json", "text/plain"}


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read_response(proc: subprocess.Popen, req_id: int, timeout_s: float = 15.0) -> dict | None:
    """Read JSON-RPC frames until the response matching ``req_id`` arrives."""
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        ready, _, _ = select.select([proc.stdout], [], [], remaining)
        if not ready:
            return None
        line = proc.stdout.readline()
        if not line:
            return None
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue
        if frame.get("id") == req_id:
            return frame


def main() -> int:
    with tempfile.TemporaryDirectory() as scratch:
        proc = subprocess.Popen(
            [sys.executable, "-m", "mcp_server.main"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            _send(proc, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke-mimetype", "version": "1"},
                },
            })
            init_resp = _read_response(proc, 1)
            if init_resp is None or init_resp.get("error"):
                print(f"FAIL mcp-mimetype-content: initialize failed: {init_resp}")
                return 1

            _send(proc, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {
                    "name": "build_index",
                    "arguments": {"project_root": scratch},
                },
            })
            resp = _read_response(proc, 2, timeout_s=30.0)
            if resp is None:
                print("FAIL mcp-mimetype-content: no tools/call response")
                return 1
            result = resp.get("result")
            if not result:
                print(f"FAIL mcp-mimetype-content: no result: {resp}")
                return 1
            blocks = result.get("content") or []
            if not blocks:
                print("FAIL mcp-mimetype-content: empty content array")
                return 1
            for i, block in enumerate(blocks):
                mime = block.get("mimeType")
                if mime not in _ACCEPTED_MIMES:
                    print(
                        f"FAIL mcp-mimetype-content: block[{i}] mimeType="
                        f"{mime!r} (expected one of {sorted(_ACCEPTED_MIMES)})"
                    )
                    return 1
            print(f"PASS mcp-mimetype-content (mimeType={blocks[0]['mimeType']})")
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
    raise SystemExit(main())
