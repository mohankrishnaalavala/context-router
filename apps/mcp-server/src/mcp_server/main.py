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
import threading
from typing import Any

from mcp_server import tools

# Shared mutex guarding stdout writes.  Both _send() and _notify() must
# acquire this lock so a response and an in-flight notification cannot
# interleave mid-line in the JSON-RPC stream.
_write_lock: Any = threading.RLock()


# ---------------------------------------------------------------------------
# Shared output schema fragments (reused across several tools)
# ---------------------------------------------------------------------------

_INDEX_OUTPUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "files": {"type": "integer", "description": "Files scanned."},
        "symbols": {"type": "integer", "description": "Symbols written."},
        "edges": {"type": "integer", "description": "Edges written."},
        "duration_seconds": {"type": "number", "description": "Elapsed indexer time."},
        "errors": {"type": "array", "items": {"type": "string"}, "description": "Up to 10 error strings."},
        "error": {"type": "string", "description": "Top-level error (present only on failure)."},
    },
}

_PACK_OUTPUT: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "description": (
        "Serialised ContextPack. When format='compact' returns {text, has_more, total_items}. "
        "On failure returns {error: <message>}."
    ),
    "properties": {
        "id": {"type": "string"},
        "mode": {"type": "string"},
        "query": {"type": "string"},
        "selected_items": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
        },
        "total_est_tokens": {"type": "integer"},
        "baseline_est_tokens": {"type": "integer"},
        "reduction_pct": {"type": "number"},
        "has_more": {"type": "boolean"},
        "total_items": {"type": "integer"},
        "text": {"type": "string", "description": "Compact-format body."},
        "error": {"type": "string"},
    },
}


# ---------------------------------------------------------------------------
# Tool registry — maps tool name → (handler_fn, description, inputSchema, outputSchema)
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
            "required": [],
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
        "outputSchema": _INDEX_OUTPUT,
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
        "outputSchema": _INDEX_OUTPUT,
    },
    "get_context_pack": {
        "fn": tools.get_context_pack,
        "description": (
            "Generate a ranked context pack for a coding task. "
            "Selects the minimum useful context across code structure, "
            "runtime evidence, and project memory for the specified mode. "
            "Use format='compact' to reduce token overhead. "
            "Use page/page_size to load items incrementally."
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
                "format": {
                    "type": "string",
                    "enum": ["json", "compact"],
                    "description": (
                        "Output format. 'json' (default) returns full serialisation. "
                        "'compact' returns path:title:excerpt lines — lower token cost."
                    ),
                    "default": "json",
                },
                "page": {
                    "type": "integer",
                    "description": "Zero-based page index for paginated results. Requires page_size > 0.",
                    "default": 0,
                },
                "page_size": {
                    "type": "integer",
                    "description": "Items per page. 0 (default) returns all ranked items.",
                    "default": 0,
                },
                "progressToken": {
                    "type": ["string", "integer"],
                    "description": (
                        "Optional token echoed back in notifications/progress "
                        "params so the client can correlate updates with this "
                        "tools/call. Notifications are only sent when the built "
                        "pack exceeds 2,000 tokens."
                    ),
                },
            },
        },
        "outputSchema": _PACK_OUTPUT,
    },
    "get_context_summary": {
        "fn": tools.get_context_summary,
        "description": (
            "Lightweight peek at a context pack — returns item count, token total, "
            "reduction %, top 5 files by confidence, and source type distribution. "
            "Use this before get_context_pack to decide if you need the full pack. "
            "Response is always under 200 tokens."
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
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "mode": {"type": "string"},
                "query": {"type": "string"},
                "item_count": {"type": "integer"},
                "total_est_tokens": {"type": "integer"},
                "baseline_est_tokens": {"type": "integer"},
                "reduction_pct": {"type": "number"},
                "top_files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "path": {"type": "string"},
                            "title": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                    },
                },
                "source_type_counts": {
                    "type": "object",
                    "additionalProperties": {"type": "integer"},
                },
                "error": {"type": "string"},
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
            "required": ["query"],
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
        "outputSchema": _PACK_OUTPUT,
    },
    "explain_selection": {
        "fn": tools.explain_selection,
        "description": (
            "Return a human-readable explanation of why each item was included "
            "in the last generated context pack, along with token reduction stats."
        ),
        "inputSchema": {
            "type": "object",
            "required": [],
            "properties": {
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "mode": {"type": "string"},
                "query": {"type": "string"},
                "total_est_tokens": {"type": "integer"},
                "baseline_est_tokens": {"type": "integer"},
                "reduction_pct": {"type": "number"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "title": {"type": "string"},
                            "source_type": {"type": "string"},
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                            "est_tokens": {"type": "integer"},
                        },
                    },
                },
                "error": {"type": "string"},
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
            "required": [],
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
        "outputSchema": _PACK_OUTPUT,
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
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "results": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                    "description": "Matching observations, serialised.",
                },
                "error": {"type": "string"},
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
            "required": [],
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
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "decisions": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "error": {"type": "string"},
            },
        },
    },
    "save_observation": {
        "fn": tools.save_observation,
        "description": (
            "Persist a coding-session observation to durable memory. "
            "Duplicate observations (same task_type + summary) are silently skipped. "
            "Secret values in commands_run are redacted automatically."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "One-line description of the task or event.",
                },
                "task_type": {
                    "type": "string",
                    "description": "Category: debug, implement, commit, handover, general.",
                    "default": "general",
                },
                "files_touched": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths modified during the task.",
                },
                "commands_run": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Shell commands executed (secrets will be redacted).",
                },
                "failures_seen": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Error or failure messages encountered.",
                },
                "fix_summary": {
                    "type": "string",
                    "description": "Short description of the fix or resolution.",
                },
                "commit_sha": {
                    "type": "string",
                    "description": "Git commit SHA if available.",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "saved": {"type": "boolean"},
                "id": {"type": ["integer", "string"]},
                "reason": {"type": "string"},
                "error": {"type": "string"},
            },
        },
    },
    "save_decision": {
        "fn": tools.save_decision,
        "description": (
            "Persist an architectural decision record (ADR) to project memory. "
            "Use this to record why a technology, pattern, or approach was chosen."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["title", "decision"],
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title for the decision.",
                },
                "decision": {
                    "type": "string",
                    "description": "The decision itself — what was chosen and why.",
                },
                "context": {
                    "type": "string",
                    "description": "Background context that motivated the decision.",
                },
                "consequences": {
                    "type": "string",
                    "description": "Trade-offs, risks, or follow-up actions.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorisation.",
                },
                "status": {
                    "type": "string",
                    "enum": ["proposed", "accepted", "deprecated", "superseded"],
                    "description": "Decision status.",
                    "default": "accepted",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "saved": {"type": "boolean"},
                "id": {"type": "string", "description": "UUID of the saved decision."},
                "error": {"type": "string"},
            },
        },
    },
    "record_feedback": {
        "fn": tools.record_feedback,
        "description": (
            "Record agent feedback for a context pack. "
            "Files reported as missing get a confidence boost in future packs; "
            "files reported as noisy get a confidence penalty. "
            "Adjustments apply after ≥ 3 feedback reports to avoid single-report noise."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["pack_id"],
            "properties": {
                "pack_id": {
                    "type": "string",
                    "description": "UUID of the ContextPack this feedback applies to.",
                },
                "useful": {
                    "type": "boolean",
                    "description": "True if the pack was helpful, false if not.",
                },
                "missing": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File or symbol paths that should have been included.",
                },
                "noisy": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File or symbol paths that were irrelevant.",
                },
                "too_much_context": {
                    "type": "boolean",
                    "description": "True if the pack contained too many items.",
                    "default": False,
                },
                "reason": {
                    "type": "string",
                    "description": "Free-text explanation.",
                },
                "files_read": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "File paths the agent actually consumed from the pack. "
                        "Enables read-coverage analytics after ≥ 5 reports."
                    ),
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "recorded": {"type": "boolean"},
                "id": {"type": "string"},
                "error": {"type": "string"},
            },
        },
    },
    "list_memory": {
        "fn": tools.list_memory,
        "description": (
            "List stored coding-session observations ordered by freshness "
            "(default), raw confidence, or recency. Returns effective_confidence "
            "for each observation so callers can see the time-decay-adjusted score."
        ),
        "inputSchema": {
            "type": "object",
            "required": [],
            "properties": {
                "sort": {
                    "type": "string",
                    "enum": ["freshness", "confidence", "recent"],
                    "description": "Sort order. Defaults to freshness (time-decay × confidence).",
                    "default": "freshness",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of observations to return.",
                    "default": 20,
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "observations": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                    "description": "Each item is a serialised Observation with effective_confidence.",
                },
                "error": {"type": "string"},
            },
        },
    },
    "mark_decision_superseded": {
        "fn": tools.mark_decision_superseded,
        "description": (
            "Mark an existing architectural decision as superseded by a newer one. "
            "Sets the old decision's status to 'superseded' and records the "
            "UUID of the replacement for audit purposes."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["old_id", "new_id"],
            "properties": {
                "old_id": {
                    "type": "string",
                    "description": "UUID of the decision being replaced.",
                },
                "new_id": {
                    "type": "string",
                    "description": "UUID of the new decision that supersedes it.",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "updated": {"type": "boolean"},
                "superseded": {"type": "string"},
                "superseded_by": {"type": "string"},
                "error": {"type": "string"},
            },
        },
    },
    "suggest_next_files": {
        "fn": tools.suggest_next_files,
        "description": (
            "Suggest the top N files to read next after receiving a context pack. "
            "Uses structural adjacency (imports, call edges) of pack items to rank "
            "candidates not already in the pack."
        ),
        "inputSchema": {
            "type": "object",
            "required": [],
            "properties": {
                "pack_id": {
                    "type": "string",
                    "description": "UUID of the pack (uses last pack if omitted).",
                },
                "project_root": {
                    "type": "string",
                    "description": "Absolute path to project root. Auto-detected when omitted.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max files to return (default 3).",
                    "default": 3,
                },
            },
        },
        "outputSchema": {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "file": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                    },
                },
                "error": {"type": "string"},
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
    """Write a single JSON-RPC response to stdout, flushed immediately.

    Mutex-guarded so it cannot interleave with an in-flight ``_notify`` call.
    """
    with _write_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def _notify(method: str, params: dict) -> None:
    """Write a JSON-RPC 2.0 notification (no ``id``) to stdout.

    Used for MCP notifications such as ``notifications/progress`` and
    ``notifications/resources/list_changed``.  Writes are guarded by the
    same ``_write_lock`` as :func:`_send` to preserve newline-delimited
    framing on the stdio transport.
    """
    with _write_lock:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
        sys.stdout.flush()


# Tools that accept progress_cb (P3-5) and/or build packs that should trigger
# a resources/list_changed notification (P3-6).  Kept as module constants so
# adding a new pack-building tool is a one-line registration.
_PROGRESS_TOOLS: frozenset[str] = frozenset({
    "get_context_pack",
})
_PACK_BUILDING_TOOLS: frozenset[str] = frozenset({
    "get_context_pack",
    "get_debug_pack",
    "generate_handover",
})


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
            "capabilities": {
                "tools": {},
                "resources": {"listChanged": True},
            },
            "serverInfo": {"name": "context-router", "version": "0.1.0"},
        })

    if method == "tools/list":
        return _ok(req_id, {
            "tools": [
                {
                    "name": name,
                    "description": info["description"],
                    "inputSchema": info["inputSchema"],
                    "outputSchema": info["outputSchema"],
                }
                for name, info in _TOOLS.items()
            ]
        })

    if method == "tools/call":
        tool_name: str = params.get("name", "")
        arguments: dict = dict(params.get("arguments") or {})

        if tool_name not in _TOOLS:
            return _err(req_id, -32601, f"Unknown tool: {tool_name!r}")

        # P3-5: wire optional progress notifications for pack-building tools.
        # Extract progressToken so the tool fn never sees it (not in its signature).
        progress_token = arguments.pop("progressToken", None)
        if progress_token is not None and tool_name in _PROGRESS_TOOLS:
            def _progress_cb(stage: str, progress: int, total: int) -> None:
                _notify("notifications/progress", {
                    "progressToken": progress_token,
                    "progress": progress,
                    "total": total,
                })
            arguments["progress_cb"] = _progress_cb

        try:
            result = _TOOLS[tool_name]["fn"](**arguments)
            is_error = isinstance(result, dict) and "error" in result

            # P3-6: announce newly-registered packs so MCP clients can refresh.
            if not is_error and tool_name in _PACK_BUILDING_TOOLS:
                _notify("notifications/resources/list_changed", {})

            return _ok(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                "isError": is_error,
            })
        except TypeError as exc:
            # Wrong arguments supplied by client
            return _err(req_id, -32602, f"Invalid params: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _err(req_id, -32603, f"Internal error: {exc}")

    if method == "ping":
        return _ok(req_id, {})

    if method == "resources/list":
        from mcp_server import resources as _resources
        project_root = params.get("project_root") or ""
        try:
            return _ok(req_id, _resources.list_resources(project_root or None))
        except Exception as exc:  # noqa: BLE001
            return _err(req_id, -32603, f"Internal error: {exc}")

    if method == "resources/read":
        from mcp_server import resources as _resources
        uri = params.get("uri", "")
        project_root = params.get("project_root") or ""
        if not uri:
            return _err(req_id, -32602, "Invalid params: 'uri' is required")
        try:
            return _ok(req_id, _resources.read_resource(uri, project_root or None))
        except ValueError as exc:
            return _err(req_id, -32602, f"Invalid params: {exc}")
        except FileNotFoundError as exc:
            return _err(req_id, -32002, f"Resource not found: {exc}")
        except Exception as exc:  # noqa: BLE001
            return _err(req_id, -32603, f"Internal error: {exc}")

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
