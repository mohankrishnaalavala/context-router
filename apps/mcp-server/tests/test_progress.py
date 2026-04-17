"""Tests for P3-5 MCP progress notifications during get_context_pack."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from contracts.models import ContextItem, ContextPack


class _DummyOrchestrator:
    """Minimal stand-in for :class:`core.orchestrator.Orchestrator`."""

    def __init__(self, *, tokens: int = 5_000) -> None:
        self._tokens = tokens

    def build_pack(
        self,
        mode: str,
        query: str,
        *,
        error_file=None,
        page: int = 0,
        page_size: int = 0,
        progress_cb=None,
    ) -> ContextPack:
        # Emit the 3 fixed milestones
        if progress_cb is not None:
            progress_cb("candidates", 1, 3)
            progress_cb("ranked", 2, 3)
            # Simulate intermediate chunk progress when tokens > 2_000
            if self._tokens > 2_000:
                for i in range(0, self._tokens, 1_000):
                    progress_cb("serializing", i, self._tokens)
            progress_cb("serialized", 3, 3)
        return ContextPack(
            mode=mode,
            query=query,
            selected_items=[
                ContextItem(
                    source_type="code",
                    repo="demo",
                    path_or_ref="src/main.py",
                    title="main",
                    reason="r",
                    confidence=0.5,
                    est_tokens=self._tokens,
                )
            ],
            total_est_tokens=self._tokens,
            baseline_est_tokens=self._tokens * 2,
            reduction_pct=50.0,
        )


def _capture_stdout():
    return io.StringIO()


class TestProgressToken:
    def test_progress_token_emits_notifications(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When progressToken is set and pack > 2_000 tokens, notifications/progress arrive."""
        from mcp_server import main as mcp_main
        from mcp_server import tools

        def fake_orch(project_root: str = ""):
            return _DummyOrchestrator(tokens=5_000)

        monkeypatch.setattr(tools, "_orchestrator", fake_orch)

        buf = _capture_stdout()
        with patch.object(mcp_main.sys, "stdout", buf):
            resp = mcp_main._handle({
                "jsonrpc": "2.0",
                "id": 42,
                "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {
                        "mode": "implement",
                        "query": "do stuff",
                        "progressToken": "job-1",
                    },
                },
            })

        # The JSON-RPC response is returned via _handle (not written to stdout)
        assert resp["result"]["isError"] is False

        # The stream captured via stdout must contain at least one
        # notifications/progress line — framed as JSON-RPC notification.
        lines = [line for line in buf.getvalue().split("\n") if line]
        progress = [json.loads(line) for line in lines if '"notifications/progress"' in line]
        assert progress, f"expected progress notifications, got: {lines}"
        for note in progress:
            assert note["jsonrpc"] == "2.0"
            assert note["method"] == "notifications/progress"
            assert note["params"]["progressToken"] == "job-1"
            assert "progress" in note["params"]
            assert "total" in note["params"]
            assert "id" not in note

    def test_no_progress_without_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without progressToken, no progress notifications are emitted."""
        from mcp_server import main as mcp_main
        from mcp_server import tools

        def fake_orch(project_root: str = ""):
            return _DummyOrchestrator(tokens=5_000)

        monkeypatch.setattr(tools, "_orchestrator", fake_orch)

        buf = _capture_stdout()
        with patch.object(mcp_main.sys, "stdout", buf):
            resp = mcp_main._handle({
                "jsonrpc": "2.0",
                "id": 43,
                "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {"mode": "implement", "query": "q"},
                },
            })
        assert resp["result"]["isError"] is False
        assert "notifications/progress" not in buf.getvalue()

    def test_small_pack_skips_intermediate_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Under 2_000 tokens the 3 fixed milestones still fire but no chunking."""
        from mcp_server import main as mcp_main
        from mcp_server import tools

        def fake_orch(project_root: str = ""):
            return _DummyOrchestrator(tokens=500)

        monkeypatch.setattr(tools, "_orchestrator", fake_orch)

        buf = _capture_stdout()
        with patch.object(mcp_main.sys, "stdout", buf):
            mcp_main._handle({
                "jsonrpc": "2.0",
                "id": 44,
                "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {
                        "mode": "implement",
                        "query": "q",
                        "progressToken": "small",
                    },
                },
            })

        lines = [line for line in buf.getvalue().split("\n") if line]
        progress_count = sum(1 for line in lines if '"notifications/progress"' in line)
        # Exactly the 3 milestones (no intermediate chunks for a 500-token pack)
        assert progress_count == 3


class TestFinalResponseShape:
    def test_progress_does_not_change_response_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The final tools/call response is unchanged by progress notifications."""
        from mcp_server import main as mcp_main
        from mcp_server import tools

        def fake_orch(project_root: str = ""):
            return _DummyOrchestrator(tokens=3_000)

        monkeypatch.setattr(tools, "_orchestrator", fake_orch)

        buf = _capture_stdout()
        with patch.object(mcp_main.sys, "stdout", buf):
            resp = mcp_main._handle({
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {
                        "mode": "implement",
                        "query": "q",
                        "progressToken": "a",
                    },
                },
            })
        assert set(resp["result"].keys()) == {"content", "isError"}
        assert resp["result"]["content"][0]["type"] == "text"
        payload = json.loads(resp["result"]["content"][0]["text"])
        assert payload["mode"] == "implement"
