"""End-to-end MCP server tests via subprocess stdio transport.

These spawn the real ``context-router-mcp`` entry point and exchange
newline-delimited JSON-RPC frames, exactly as an MCP client would.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

import pytest
from contracts.models import ContextItem, ContextPack
from core.pack_store import PackStore


def _make_pack(query: str = "sub") -> ContextPack:
    return ContextPack(
        mode="implement",
        query=query,
        selected_items=[
            ContextItem(
                source_type="code",
                repo="demo",
                path_or_ref="src/a.py",
                title="a",
                reason="r",
                confidence=0.5,
                est_tokens=10,
            )
        ],
        total_est_tokens=10,
        baseline_est_tokens=30,
        reduction_pct=66.0,
    )


@pytest.fixture()
def mcp_proc(tmp_path: Path) -> Iterator[subprocess.Popen[str]]:
    """Spawn the MCP server as a subprocess and yield the Popen handle."""
    env = {}
    import os
    env.update(os.environ)
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
        yield proc
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _send(proc: subprocess.Popen[str], req: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()


def _recv_line(proc: subprocess.Popen[str], timeout: float = 5.0) -> dict:
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("MCP server closed stdout unexpectedly")
    return json.loads(line.strip())


def _recv_until(
    proc: subprocess.Popen[str], req_id: int, timeout: float = 10.0,
) -> tuple[list[dict], dict]:
    """Read lines until a response with ``req_id`` arrives.

    Returns ``(notifications, response)``.
    """
    notifications: list[dict] = []
    deadline = time.monotonic() + timeout
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError("Timed out waiting for MCP response")
        msg = _recv_line(proc, timeout=deadline - time.monotonic())
        if msg.get("id") == req_id:
            return notifications, msg
        # Everything else is a notification or a stray response
        if "method" in msg and "id" not in msg:
            notifications.append(msg)


class TestInitialize:
    def test_initialize_declares_resources_capability(
        self, mcp_proc: subprocess.Popen[str],
    ) -> None:
        _send(mcp_proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _, resp = _recv_until(mcp_proc, 1)
        caps = resp["result"]["capabilities"]
        assert "resources" in caps
        assert caps["resources"] == {"listChanged": True}
        assert "tools" in caps


class TestProgressNotifications:
    def test_progress_notifications_precede_response(
        self, tmp_project_dir: Path
    ) -> None:
        """At least one notifications/progress arrives before the tools/call reply.

        This test spawns a dedicated subprocess with the
        ``CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS`` env var lowered so the synthetic
        (tiny) fixture still exercises the streaming path.  Production defaults
        (>=500 tokens) are covered by Phase-4 mcp-pack-streams-large smoke.
        """
        # Initialize DB in the project dir so build_pack can open it.
        (tmp_project_dir / ".context-router").mkdir(exist_ok=True)
        from storage_sqlite.database import Database
        db_path = tmp_project_dir / ".context-router" / "context-router.db"
        if not db_path.exists():
            db = Database(db_path)
            db.initialize()
            db.close()

        import os as _os
        env = _os.environ.copy()
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
            _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            _recv_until(proc, 1)

            _send(proc, {
                "jsonrpc": "2.0", "id": 5, "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {
                        "mode": "implement",
                        "query": "test",
                        "project_root": str(tmp_project_dir),
                        "progressToken": "e2e",
                    },
                },
            })
            notes, resp = _recv_until(proc, 5, timeout=30.0)
            assert resp["result"]["isError"] is False
            progress_notes = [n for n in notes if n.get("method") == "notifications/progress"]
            assert progress_notes, f"expected at least one progress notification, got: {notes}"
            for n in progress_notes:
                assert n["params"]["progressToken"] == "e2e"
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


class TestResourcesRoundTrip:
    def test_saved_pack_is_listed_and_readable(
        self, mcp_proc: subprocess.Popen[str], tmp_path: Path
    ) -> None:
        pack = _make_pack()
        PackStore(tmp_path).save(pack)
        stored_text = (tmp_path / ".context-router" / "packs" / f"{pack.id}.json").read_text()

        # initialize handshake
        _send(mcp_proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        _recv_until(mcp_proc, 1)

        # resources/list
        _send(mcp_proc, {
            "jsonrpc": "2.0", "id": 2, "method": "resources/list",
            "params": {"project_root": str(tmp_path)},
        })
        _, resp_list = _recv_until(mcp_proc, 2)
        uris = [r["uri"] for r in resp_list["result"]["resources"]]
        assert f"context-router://packs/{pack.id}" in uris
        assert len(uris) >= 1

        # resources/read — byte-identical to last-pack.json
        _send(mcp_proc, {
            "jsonrpc": "2.0", "id": 3, "method": "resources/read",
            "params": {
                "uri": f"context-router://packs/{pack.id}",
                "project_root": str(tmp_path),
            },
        })
        _, resp_read = _recv_until(mcp_proc, 3)
        text = resp_read["result"]["contents"][0]["text"]
        assert text == stored_text
