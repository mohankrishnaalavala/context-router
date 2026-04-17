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
    def test_returns_all_sixteen_tools(self):
        resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = {t["name"] for t in resp["result"]["tools"]}
        assert names == {
            "build_index",
            "update_index",
            "get_context_pack",
            "get_context_summary",
            "get_debug_pack",
            "get_minimal_context",
            "explain_selection",
            "generate_handover",
            "search_memory",
            "get_decisions",
            "save_observation",
            "save_decision",
            "list_memory",
            "mark_decision_superseded",
            "record_feedback",
            "suggest_next_files",
        }

    def test_each_tool_has_schema(self):
        resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        for tool in resp["result"]["tools"]:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

    def test_each_tool_declares_required_array(self):
        resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        for tool in resp["result"]["tools"]:
            schema = tool["inputSchema"]
            assert "required" in schema, f"{tool['name']} missing required array"
            assert isinstance(schema["required"], list), (
                f"{tool['name']} required must be a list"
            )

    def test_each_tool_has_output_schema(self):
        resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        for tool in resp["result"]["tools"]:
            assert "outputSchema" in tool, f"{tool['name']} missing outputSchema"
            assert isinstance(tool["outputSchema"], dict)
            assert tool["outputSchema"].get("type") == "object", (
                f"{tool['name']} outputSchema must be type=object"
            )


# ---------------------------------------------------------------------------
# tools/call
# ---------------------------------------------------------------------------

class TestToolsCall:
    def test_unknown_tool_is_error(self):
        resp = _handle({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "no_such_tool", "arguments": {}},
        })
        # Unknown tool must be a JSON-RPC error response (not a successful result)
        assert "error" in resp
        assert resp["error"]["code"] == -32601
        assert "no_such_tool" in resp["error"]["message"]

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

    def test_invalid_arguments_returns_jsonrpc_error(self):
        # update_index requires changed_files — omitting it must return a JSON-RPC error
        resp = _handle({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "update_index", "arguments": {}},
        })
        assert "error" in resp
        assert resp["error"]["code"] == -32602


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
