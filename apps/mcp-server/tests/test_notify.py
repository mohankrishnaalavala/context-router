"""Tests for the _notify JSON-RPC notification helper."""

from __future__ import annotations

import io
import json
import threading
from unittest.mock import patch


def test_notify_emits_jsonrpc_notification_without_id() -> None:
    """_notify must emit a JSON-RPC 2.0 notification with no `id` field."""
    from mcp_server import main as mcp_main

    buf = io.StringIO()
    with patch.object(mcp_main.sys, "stdout", buf):
        mcp_main._notify("notifications/progress", {"progressToken": "t1", "progress": 1, "total": 3})

    raw = buf.getvalue()
    assert raw.endswith("\n"), "notification must be newline-terminated"
    payload = json.loads(raw.strip())
    assert payload["jsonrpc"] == "2.0"
    assert payload["method"] == "notifications/progress"
    assert payload["params"] == {"progressToken": "t1", "progress": 1, "total": 3}
    assert "id" not in payload, "notifications must not carry an `id` field"


def test_notify_holds_same_mutex_as_send() -> None:
    """Concurrent _notify and _send writes must not interleave.

    This smoke-tests that both acquire the same lock.  We monkey-patch the
    underlying lock to record acquisition from both call paths.
    """
    from mcp_server import main as mcp_main

    order: list[str] = []

    class _TrackingLock:
        def __init__(self) -> None:
            self._inner = threading.RLock()

        def __enter__(self):
            self._inner.acquire()
            order.append("enter")
            return self

        def __exit__(self, exc_type, exc, tb):
            order.append("exit")
            self._inner.release()
            return False

    buf = io.StringIO()
    with patch.object(mcp_main, "_write_lock", _TrackingLock()):
        with patch.object(mcp_main.sys, "stdout", buf):
            mcp_main._notify("notifications/test", {"k": "v"})
            mcp_main._send({"jsonrpc": "2.0", "id": 1, "result": {}})

    assert order == ["enter", "exit", "enter", "exit"], (
        "each write must acquire and release the lock"
    )


def test_notify_does_not_interleave_under_concurrency() -> None:
    """Concurrent _notify calls across threads must write complete JSON lines."""
    from mcp_server import main as mcp_main

    buf = io.StringIO()

    def send_many(prefix: str) -> None:
        for i in range(50):
            mcp_main._notify("notifications/progress", {"progressToken": prefix, "progress": i})

    with patch.object(mcp_main.sys, "stdout", buf):
        threads = [threading.Thread(target=send_many, args=(f"t{n}",)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    lines = [line for line in buf.getvalue().split("\n") if line]
    assert len(lines) == 200
    for line in lines:
        # Every line must parse as valid JSON-RPC notification — no interleaving
        obj = json.loads(line)
        assert obj["jsonrpc"] == "2.0"
        assert obj["method"] == "notifications/progress"
