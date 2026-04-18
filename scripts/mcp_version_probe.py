"""Smoke harness: verify initialize.serverInfo.version reflects package.

Drives ``apps/mcp-server/src/mcp_server/main.py`` via a stdio JSON-RPC
session, performs ``initialize``, and asserts the returned
``serverInfo.version`` (a) matches ``importlib.metadata.version(
'context-router-mcp-server')`` and (b) is SemVer-shaped (``^\\d+\\.\\d+\\.\\d+``).

Prints ``PASS mcp-serverinfo-version (version=<value>)`` on success,
``FAIL mcp-serverinfo-version: <reason>`` on failure.  Used by
``scripts/smoke-v3.sh`` under the ``mcp-serverinfo-version`` outcome.
"""

from __future__ import annotations

import json
import re
import select
import subprocess
import sys
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version


_SEMVER = re.compile(r"^\d+\.\d+\.\d+")


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read_response(proc: subprocess.Popen, req_id: int, timeout_s: float = 15.0) -> dict | None:
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
    try:
        expected = pkg_version("context-router-mcp-server")
    except PackageNotFoundError:
        print(
            "FAIL mcp-serverinfo-version: package "
            "'context-router-mcp-server' is not installed"
        )
        return 1

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
                "clientInfo": {"name": "smoke-version", "version": "1"},
            },
        })
        resp = _read_response(proc, 1)
        if resp is None:
            print("FAIL mcp-serverinfo-version: no initialize response")
            return 1
        if resp.get("error"):
            print(f"FAIL mcp-serverinfo-version: initialize error: {resp['error']}")
            return 1
        server_info = (resp.get("result") or {}).get("serverInfo") or {}
        observed = server_info.get("version")
        if not observed:
            print(f"FAIL mcp-serverinfo-version: missing serverInfo.version: {resp}")
            return 1
        if observed != expected:
            print(
                f"FAIL mcp-serverinfo-version: observed {observed!r} "
                f"!= installed package version {expected!r}"
            )
            return 1
        if not _SEMVER.match(observed):
            print(
                f"FAIL mcp-serverinfo-version: version {observed!r} is "
                "not SemVer-shaped (^\\d+\\.\\d+\\.\\d+)"
            )
            return 1
        print(f"PASS mcp-serverinfo-version (version={observed})")
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
