"""MCP stdio server for context-router.

Implements the Model Context Protocol over stdin/stdout JSON-RPC 2.0,
exposing the 8 context-router tools to any MCP-compatible AI coding agent.

Protocol flow:
  1. Client → initialize         (server returns capabilities + server info)
  2. Client → initialized        (notification, no response)
  3. Client → tools/list         (server returns tool schemas)
  4. Client → tools/call         (server dispatches, returns result)
"""

from __future__ import annotations

import json
import sys
from typing import Any

from mcp_server import tools


# ---------------------------------------------------------------------------
# Tool registry — maps tool name → (handler_fn, description, inputSchema)
# ---------------------------------------------------------------------------

_TOOLS: dict[str, dict[str, Any]] = {
    "build_index": {
        "fn": tools.build_index,
        "description": (
            "Full re-index of a repository. Scans all source files, "
            "extracts symbols and edges, and stores results in the local "
            "SQLite database."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
                "repo_name": {
                    "type": "string",
                    "description": "Logical repository name.",
                    "default": "default",
                },
            },
        },
    },
    "update_index": {
        "fn": tools.update_index,
        "description": (
            "Incremental re-index for a list of changed files. "
            "Only re-analyzes the supplied paths — faster than a full build."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["changed_files"],
            "properties": {
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths to re-index (absolute or relative to cwd).",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
                "repo_name": {
                    "type": "string",
                    "description": "Logical repository name.",
                    "default": "default",
                },
            },
        },
    },
    "get_context_pack": {
        "fn": tools.get_context_pack,
        "description": (
            "Generate a ranked context pack for a coding task. "
            "Selects the minimum useful context across code structure, "
            "runtime evidence, and project memory for the specified mode."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["mode"],
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["review", "implement", "debug", "handover"],
                    "description": "Task mode that controls ranking strategy.",
                },
                "query": {
                    "type": "string",
                    "description": "Free-text task description (used for relevance scoring).",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
    },
    "get_debug_pack": {
        "fn": tools.get_debug_pack,
        "description": (
            "Generate a debug-mode context pack, optionally parsing an error file. "
            "Supports JUnit XML, Python/Java/.NET stack traces, and log files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text description of the bug.",
                },
                "error_file": {
                    "type": "string",
                    "description": (
                        "Path to a JUnit XML, stack trace text, or log file. "
                        "Parsed to extract RuntimeSignals that boost relevant file scores."
                    ),
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
    },
    "explain_selection": {
        "fn": tools.explain_selection,
        "description": (
            "Return a human-readable explanation of why each item was included "
            "in the last generated context pack, along with token reduction stats."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
    },
    "generate_handover": {
        "fn": tools.generate_handover,
        "description": (
            "Generate a handover context pack combining recent changes, "
            "memory observations, and architectural decisions. "
            "Designed to orient a new agent session."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional task description for the handover context.",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
    },
    "search_memory": {
        "fn": tools.search_memory,
        "description": "Full-text search stored coding-session observations.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {
                    "type": "string",
                    "description": "FTS5 query string.",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
    },
    "get_decisions": {
        "fn": tools.get_decisions,
        "description": (
            "Search or list stored architectural decision records (ADRs). "
            "Returns all decisions when query is empty."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "FTS5 query string. Returns all decisions when omitted.",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 response helpers
# ---------------------------------------------------------------------------

def _ok(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _send(obj: dict) -> None:
    """Write a single JSON-RPC response to stdout, flushed immediately."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# MCP request dispatch
# ---------------------------------------------------------------------------

def _handle(request: dict) -> dict | None:
    """Dispatch one JSON-RPC request and return a response dict (or None for notifications)."""
    method: str = request.get("method", "")
    req_id = request.get("id")
    params: dict = request.get("params") or {}

    # Notifications have no id — must not send a response
    if req_id is None:
        return None

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "context-router", "version": "0.1.0"},
        })

    if method == "tools/list":
        return _ok(req_id, {
            "tools": [
                {
                    "name": name,
                    "description": info["description"],
                    "inputSchema": info["inputSchema"],
                }
                for name, info in _TOOLS.items()
            ]
        })

    if method == "tools/call":
        tool_name: str = params.get("name", "")
        arguments: dict = params.get("arguments") or {}

        if tool_name not in _TOOLS:
            return _ok(req_id, {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name!r}"}],
                "isError": True,
            })

        try:
            result = _TOOLS[tool_name]["fn"](**arguments)
            is_error = isinstance(result, dict) and "error" in result
            return _ok(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError": is_error,
            })
        except TypeError as exc:
            # Wrong arguments supplied by client
            return _ok(req_id, {
                "content": [{"type": "text", "text": f"Invalid arguments: {exc}"}],
                "isError": True,
            })
        except Exception as exc:  # noqa: BLE001
            return _ok(req_id, {
                "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                "isError": True,
            })

    if method == "ping":
        return _ok(req_id, {})

    return _err(req_id, -32601, f"Method not found: {method!r}")


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Start the context-router MCP server over stdio transport.

    Reads JSON-RPC 2.0 requests from stdin (one per line) and writes
    responses to stdout.  Errors are logged to stderr so they don't
    contaminate the JSON stream.
    """
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            _send(_err(None, -32700, f"Parse error: {exc}"))
            continue

        if not isinstance(request, dict):
            _send(_err(None, -32600, "Invalid request: expected a JSON object"))
            continue

        try:
            response = _handle(request)
        except Exception as exc:  # noqa: BLE001
            print(f"Unhandled error: {exc}", file=sys.stderr)
            response = _err(request.get("id"), -32603, f"Internal error: {exc}")

        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
