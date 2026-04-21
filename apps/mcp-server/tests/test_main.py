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

    def test_server_version_matches_installed_package(self):
        """Phase-4 mcp-serverinfo-version: serverInfo.version comes from
        importlib.metadata, not a hard-coded literal."""
        import re
        from importlib.metadata import version as pkg_version

        expected = pkg_version("context-router-mcp-server")
        resp = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        observed = resp["result"]["serverInfo"]["version"]
        assert observed == expected, (
            f"serverInfo.version {observed!r} does not match installed "
            f"package version {expected!r}"
        )
        # Must be a SemVer-ish string (accept both 2.x during dev and 3.x).
        assert re.match(r"^\d+\.\d+\.\d+", observed), (
            f"serverInfo.version {observed!r} is not SemVer-shaped"
        )

    def test_server_version_is_not_hardcoded_stub(self):
        """Guard against accidental regression to the old ``0.1.0`` literal."""
        resp = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert resp["result"]["serverInfo"]["version"] != "0.1.0"
        assert resp["result"]["serverInfo"]["version"] != "0.0.0+unknown"

    def test_falls_back_to_cli_bundle_version_when_mcp_server_dist_missing(self, monkeypatch):
        """v3.3.1: when `context-router-mcp-server` is absent (the
        production path — PyPI/pipx/brew users install `context-router-cli`
        only and the mcp_server module ships bundled via hatch force-include),
        serverInfo.version MUST resolve to `context-router-cli`'s version.

        Pre-v3.3.1, this raised ImportError and `context-router mcp`
        could not start on any fresh end-user install.
        """
        import importlib
        import importlib.metadata as md
        import sys

        real_version = md.version

        def _fake(name: str) -> str:
            if name == "context-router-mcp-server":
                raise md.PackageNotFoundError(name)
            if name == "context-router-cli":
                return "9.9.9"
            return real_version(name)

        monkeypatch.setattr(md, "version", _fake)
        monkeypatch.delitem(sys.modules, "mcp_server.main", raising=False)
        try:
            module = importlib.import_module("mcp_server.main")
            assert module._SERVER_VERSION == "9.9.9"
        finally:
            monkeypatch.setattr(md, "version", real_version)
            sys.modules.pop("mcp_server.main", None)
            importlib.import_module("mcp_server.main")

    def test_import_fails_clearly_when_both_dists_missing(self, monkeypatch):
        """Negative case: if NEITHER `context-router-mcp-server` NOR
        `context-router-cli` is installed (the module is being imported
        from a context where context-router was never pip-installed at
        all), import MUST raise ImportError with a clear message naming
        both distributions. This is the boundary that keeps silent stub
        versions from riding into production handshakes.
        """
        import importlib
        import importlib.metadata as md
        import sys

        real_version = md.version

        def _raise_both(name: str) -> str:
            if name in ("context-router-mcp-server", "context-router-cli"):
                raise md.PackageNotFoundError(name)
            return real_version(name)

        monkeypatch.setattr(md, "version", _raise_both)
        monkeypatch.delitem(sys.modules, "mcp_server.main", raising=False)
        try:
            with pytest.raises(ImportError, match="context-router-cli"):
                importlib.import_module("mcp_server.main")
        finally:
            monkeypatch.setattr(md, "version", real_version)
            sys.modules.pop("mcp_server.main", None)
            importlib.import_module("mcp_server.main")


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
            "get_call_chain",
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

    def test_content_block_includes_mimetype(self, tmp_path):
        """Phase-4 mcp-mimetype-content: every text content block advertises
        its MIME type — json-serialised tool output gets application/json."""
        resp = _handle({
            "jsonrpc": "2.0", "id": 40, "method": "tools/call",
            "params": {"name": "build_index", "arguments": {"project_root": str(tmp_path)}},
        })
        blocks = resp["result"]["content"]
        assert blocks, "tools/call must return at least one content block"
        for block in blocks:
            assert "mimeType" in block, (
                f"content block missing mimeType: {block!r}"
            )
            assert block["mimeType"] in {"application/json", "text/plain"}, (
                f"unexpected mimeType: {block['mimeType']!r}"
            )
        # Our current toolset is all-JSON — assert the concrete value.
        assert blocks[0]["mimeType"] == "application/json"

    def test_mimetype_present_for_every_tool_on_invalid_args(self):
        """Even tool calls that fail validation MUST return a JSON-RPC
        error, never a content block without mimeType."""
        # Invalid args → JSON-RPC error, not a content block.  Ensures the
        # mimeType change doesn't leak into the error path.
        resp = _handle({
            "jsonrpc": "2.0", "id": 41, "method": "tools/call",
            "params": {"name": "update_index", "arguments": {}},
        })
        assert "error" in resp
        assert "result" not in resp

    def test_mimetype_on_error_result(self, tmp_path):
        """When the tool fn returns an error dict (not a raised exception),
        the content block is still wrapped with mimeType, and isError=True."""
        resp = _handle({
            "jsonrpc": "2.0", "id": 42, "method": "tools/call",
            "params": {"name": "build_index", "arguments": {"project_root": str(tmp_path)}},
        })
        block = resp["result"]["content"][0]
        assert block["type"] == "text"
        assert block["mimeType"] == "application/json"
        assert resp["result"]["isError"] is True

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
