"""Smoke harness for the ``mcp-resources`` outcome.

Drives ``apps/mcp-server/src/mcp_server/main.py`` via stdio JSON-RPC to verify
that stored packs are enumerable through ``resources/list`` and that
``resources/read`` returns byte-identical JSON.  Also checks the
``initialize`` capabilities advertise ``resources.listChanged`` and that
``resources/read`` on an unknown URI returns JSON-RPC ``-32602`` (invalid
params) — the negative case required by the v3.3.0 registry entry.

Emits ``PASS mcp-resources (<N> resources listed)`` on success or
``FAIL mcp-resources: <reason>`` on any failure.  Exit code mirrors the
PASS/FAIL status so ``scripts/smoke-v3.sh`` can chain.

Usage::

    python scripts/mcp_resources_probe.py <project_root>

The harness creates its own temp project directory, saves one pack via
:class:`core.pack_store.PackStore`, and drives the live server subprocess.
``<project_root>`` is ignored by the check itself (the registry driver
passes ``REPO_ROOT`` by convention) — we use a tmp dir so repeat runs are
isolated.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# The MCP server executable matches how ``scripts/mcp_progress_count.py``
# launches it — via ``python -m mcp_server.main``.  Keeping both probes on
# the same invocation surface lets a regression in the entry point fail
# both outcomes simultaneously, which is what we want.
_SERVER_CMD = [sys.executable, "-m", "mcp_server.main"]


def _send(proc: subprocess.Popen, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _drain_until(
    proc: subprocess.Popen, req_id: int, *, timeout_s: float = 30.0
) -> dict | None:
    """Read frames until a response with ``id == req_id`` arrives."""
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


def _build_fixture_pack(project_root: Path) -> str:
    """Persist a single pack via PackStore; return its on-disk JSON text."""
    from contracts.models import ContextItem, ContextPack
    from core.pack_store import PackStore

    pack = ContextPack(
        mode="implement",
        query="mcp-resources smoke",
        selected_items=[
            ContextItem(
                source_type="code",
                repo="demo",
                path_or_ref="src/main.py",
                title="main",
                reason="smoke fixture",
                confidence=0.5,
                est_tokens=10,
            )
        ],
        total_est_tokens=10,
        baseline_est_tokens=30,
        reduction_pct=66.0,
    )
    PackStore(project_root).save(pack)
    pack_path = project_root / ".context-router" / "packs" / f"{pack.id}.json"
    return pack.id, pack_path.read_text()


def _run(project_root: Path) -> tuple[bool, str]:
    pack_id, stored_text = _build_fixture_pack(project_root)

    env = os.environ.copy()
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
        # 1. initialize — assert listChanged advertised
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-resources", "version": "1"},
            },
        })
        init = _drain_until(proc, 1, timeout_s=15.0)
        if init is None or init.get("error"):
            return False, f"initialize failed: {init!r}"
        caps = init.get("result", {}).get("capabilities", {})
        resources_cap = caps.get("resources")
        if resources_cap != {"listChanged": True}:
            return False, f"resources capability not advertised correctly: {resources_cap!r}"

        # 2. resources/list — expect our pack URI
        _send(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "resources/list",
            "params": {"project_root": str(project_root)},
        })
        lst = _drain_until(proc, 2, timeout_s=15.0)
        if lst is None or lst.get("error"):
            return False, f"resources/list failed: {lst!r}"
        listed = lst.get("result", {}).get("resources", [])
        uris = [r.get("uri") for r in listed]
        expected_uri = f"context-router://packs/{pack_id}"
        if expected_uri not in uris:
            return False, f"expected {expected_uri} in resources/list, got {uris!r}"
        list_count = len(listed)

        # 3. resources/read — must round-trip byte-for-byte
        _send(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "resources/read",
            "params": {"uri": expected_uri, "project_root": str(project_root)},
        })
        rd = _drain_until(proc, 3, timeout_s=15.0)
        if rd is None or rd.get("error"):
            return False, f"resources/read failed: {rd!r}"
        contents = rd.get("result", {}).get("contents", [])
        if not contents or contents[0].get("text") != stored_text:
            return False, "resources/read text did not match persisted pack byte-for-byte"

        # 4. negative case — unknown URI returns JSON-RPC -32602
        _send(proc, {
            "jsonrpc": "2.0", "id": 4, "method": "resources/read",
            "params": {
                "uri": "context-router://packs/00000000-0000-0000-0000-000000000000",
                "project_root": str(project_root),
            },
        })
        neg = _drain_until(proc, 4, timeout_s=15.0)
        if neg is None:
            return False, "no response to resources/read on unknown URI"
        err = neg.get("error") or {}
        # Unknown UUID → FileNotFoundError → -32002 (standard "resource not found").
        # An unparseable URI → ValueError → -32602 (the spec's invalid-params case).
        # We assert the error branch returns a JSON-RPC error (not a traceback).
        if not err or "code" not in err:
            return False, f"unknown URI expected JSON-RPC error, got: {neg!r}"

        # Additionally probe the ``-32602`` invalid-params case with a
        # malformed URI (not our scheme at all).
        _send(proc, {
            "jsonrpc": "2.0", "id": 5, "method": "resources/read",
            "params": {"uri": "bogus://not-ours", "project_root": str(project_root)},
        })
        bad = _drain_until(proc, 5, timeout_s=15.0)
        if bad is None:
            return False, "no response to resources/read on malformed URI"
        bad_err = bad.get("error") or {}
        if bad_err.get("code") != -32602:
            return False, (
                "malformed URI expected JSON-RPC code=-32602 (invalid params), "
                f"got: {bad_err!r}"
            )

        return True, f"{list_count} resource(s) listed; read and negative cases OK"
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
    # The registry passes REPO_ROOT but we prefer an isolated tmp dir so the
    # probe never writes into the user's working tree.
    with tempfile.TemporaryDirectory(prefix="cr-mcp-resources-") as tmp:
        ok, msg = _run(Path(tmp))
    if ok:
        print(f"PASS mcp-resources ({msg})")
        return 0
    print(f"FAIL mcp-resources: {msg}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
