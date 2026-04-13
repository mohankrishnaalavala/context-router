"""Tests for the MCP server JSON-RPC dispatch layer."""

from __future__ import annotations

import json

import pytest


def _handle(request: dict):
    """Call the internal _handle function directly."""
    from mcp_server.main import _handle as handle
    return handle(request)


# ---------------------------------------------------------------------------
# Protocol handshake
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_returns_protocol_version(self):
        resp = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp["result"]["protocolVersion"] == "2024-11-05"
        assert resp["result"]["serverInfo"]["name"] == "context-router"

    def test_capabilities_include_tools(self):
        resp = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert "tools" in resp["result"]["capabilities"]


class TestPing:
    def test_returns_empty_result(self):
        resp = _handle({"jsonrpc": "2.0", "id": 99, "method": "ping"})
        assert resp["result"] == {}
        assert resp["id"] == 99


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------

class TestToolsList:
    def test_returns_all_thirteen_tools(self):
        resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == {
            "build_index",
            "update_index",
            "get_context_pack",
            "get_debug_pack",
            "explain_selection",
            "generate_handover",
            "search_memory",
            "get_decisions",
            "save_observation",
            "save_decision",
            "list_memory",
            "mark_decision_superseded",
            "record_feedback",
        }

    def test_each_tool_has_schema(self):
        resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        for tool in resp["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------

class TestToolsCall:
    def test_unknown_tool_is_error(self):
        resp = _handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        })
        assert resp["result"]["isError"] is True
        assert "Unknown tool" in resp["result"]["content"][0]["text"]

    def test_result_is_json_text(self, tmp_path):
        # build_index with a non-existent DB returns an error dict — still valid JSON
        resp = _handle({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "build_index", "arguments": {"project_root": str(tmp_path)}},
        })
        content_text = resp["result"]["content"][0]["text"]
        # Must be valid JSON
        parsed = json.loads(content_text)
        assert "error" in parsed

    def test_invalid_arguments_returns_error(self):
        # update_index requires changed_files — omitting it should return isError
        resp = _handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "update_index", "arguments": {}},
        })
        assert resp["result"]["isError"] is True


# ---------------------------------------------------------------------------
# Notifications (no response)
# ---------------------------------------------------------------------------

class TestNotifications:
    def test_initialized_notification_returns_none(self):
        # Notifications have no id
        resp = _handle({"jsonrpc": "2.0", "method": "initialized"})
        assert resp is None

    def test_unknown_notification_returns_none(self):
        resp = _handle({"jsonrpc": "2.0", "method": "something/happened"})
        assert resp is None


# ---------------------------------------------------------------------------
# Unknown method with id
# ---------------------------------------------------------------------------

class TestUnknownMethod:
    def test_returns_method_not_found_error(self):
        resp = _handle({"jsonrpc": "2.0", "id": 10, "method": "foo/bar"})
        assert resp["error"]["code"] == -32601
        assert "foo/bar" in resp["error"]["message"]
