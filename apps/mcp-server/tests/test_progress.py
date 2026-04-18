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
        use_embeddings: bool = False,
        progress: bool = True,
        progress_cb=None,
        download_progress_cb=None,
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
        """At-threshold (500 tokens) emits the 3 milestones with no chunking."""
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


class TestStreamingGate:
    """Phase-4 mcp-pack-streams-large — token-threshold gate behaviour."""

    def test_tiny_pack_emits_zero_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Packs under 500 tokens emit NO progress notifications (negative case)."""
        from mcp_server import main as mcp_main
        from mcp_server import tools

        def fake_orch(project_root: str = ""):
            return _DummyOrchestrator(tokens=100)

        monkeypatch.setattr(tools, "_orchestrator", fake_orch)
        # Clear any test-harness env override.
        monkeypatch.delenv("CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS", raising=False)

        buf = _capture_stdout()
        with patch.object(mcp_main.sys, "stdout", buf):
            mcp_main._handle({
                "jsonrpc": "2.0",
                "id": 55,
                "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {
                        "mode": "implement",
                        "query": "q",
                        "progressToken": "tiny",
                    },
                },
            })

        lines = [line for line in buf.getvalue().split("\n") if line]
        progress_count = sum(1 for line in lines if '"notifications/progress"' in line)
        assert progress_count == 0, f"tiny packs must not emit progress; got {progress_count}"

    def test_large_pack_emits_at_least_two_progress(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Packs over 2000 tokens emit ≥2 progress notifications (threshold)."""
        from mcp_server import main as mcp_main
        from mcp_server import tools

        def fake_orch(project_root: str = ""):
            return _DummyOrchestrator(tokens=5_000)

        monkeypatch.setattr(tools, "_orchestrator", fake_orch)
        monkeypatch.delenv("CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS", raising=False)

        buf = _capture_stdout()
        with patch.object(mcp_main.sys, "stdout", buf):
            mcp_main._handle({
                "jsonrpc": "2.0",
                "id": 56,
                "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {
                        "mode": "implement",
                        "query": "q",
                        "progressToken": "big",
                    },
                },
            })

        lines = [line for line in buf.getvalue().split("\n") if line]
        progress_count = sum(1 for line in lines if '"notifications/progress"' in line)
        assert progress_count >= 2, (
            f"large packs must stream >=2 notifications; got {progress_count}"
        )

    def test_threshold_env_override_lowers_gate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS=0 forces streaming even for tiny packs."""
        from mcp_server import main as mcp_main
        from mcp_server import tools

        def fake_orch(project_root: str = ""):
            return _DummyOrchestrator(tokens=42)

        monkeypatch.setattr(tools, "_orchestrator", fake_orch)
        monkeypatch.setenv("CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS", "0")

        buf = _capture_stdout()
        with patch.object(mcp_main.sys, "stdout", buf):
            mcp_main._handle({
                "jsonrpc": "2.0",
                "id": 57,
                "method": "tools/call",
                "params": {
                    "name": "get_context_pack",
                    "arguments": {
                        "mode": "implement",
                        "query": "q",
                        "progressToken": "forced",
                    },
                },
            })

        lines = [line for line in buf.getvalue().split("\n") if line]
        progress_count = sum(1 for line in lines if '"notifications/progress"' in line)
        assert progress_count >= 2, (
            f"env override must enable streaming; got {progress_count}"
        )

    def test_invalid_env_override_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Malformed env value warns to stderr and uses the default threshold."""
        from mcp_server import main as mcp_main

        monkeypatch.setenv("CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS", "not-a-number")
        # Capture stderr by calling the helper directly — no subprocess needed.
        threshold = mcp_main._stream_min_tokens()
        assert threshold == mcp_main._STREAM_PROGRESS_MIN_TOKENS_DEFAULT
        captured = capsys.readouterr()
        assert "invalid CONTEXT_ROUTER_MCP_STREAM_MIN_TOKENS" in captured.err

    def test_extract_total_tokens_from_json_pack(self) -> None:
        """_extract_total_tokens pulls the int from a full JSON pack dict."""
        from mcp_server import main as mcp_main
        assert mcp_main._extract_total_tokens({"total_est_tokens": 1234}) == 1234

    def test_extract_total_tokens_from_compact_text(self) -> None:
        """_extract_total_tokens infers from text length for compact format."""
        from mcp_server import main as mcp_main
        payload = {"text": "x" * 4_000, "total_items": 1, "has_more": False}
        # 4000 chars // 4 ≈ 1000 token proxy.
        assert mcp_main._extract_total_tokens(payload) == 1000

    def test_extract_total_tokens_missing_returns_zero(self) -> None:
        from mcp_server import main as mcp_main
        assert mcp_main._extract_total_tokens({"other": "shape"}) == 0
        assert mcp_main._extract_total_tokens("not a dict") == 0

    def test_progress_gate_swallows_notify_errors(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Silent-failure rule: a failing _notify_progress must not crash flush."""
        from mcp_server import main as mcp_main

        def _boom(*_a: object, **_kw: object) -> None:
            raise RuntimeError("stdout is broken")

        monkeypatch.setattr(mcp_main, "_notify_progress", _boom)
        gate = mcp_main._ProgressGate("tok")
        gate.capture("candidates", 1, 3)
        gate.capture("ranked", 2, 3)
        gate.capture("serialized", 3, 3)
        # Must not raise even though _notify_progress blows up every call.
        emitted = gate.flush_if_large(total_tokens=5_000)
        # No notifications succeeded (all raised) but flush_if_large itself
        # returned normally after logging to stderr for each failure.
        assert emitted == 0
        err = capsys.readouterr().err
        assert err.count("progress notification failed") == 3


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
