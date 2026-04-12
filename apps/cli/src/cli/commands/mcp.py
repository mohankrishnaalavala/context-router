"""context-router mcp command — starts the local MCP server over stdio."""

from __future__ import annotations

import typer

mcp_app = typer.Typer(help="Start the context-router MCP server over stdio transport.")


@mcp_app.callback(invoke_without_command=True)
def mcp() -> None:
    """Start the context-router MCP server over stdio transport.

    Reads JSON-RPC 2.0 requests from stdin and writes responses to stdout.
    This is the entry point for MCP-compatible AI coding agents (Claude Code,
    Copilot, Codex) to discover and call context-router tools.

    Example configuration for Claude Code (.mcp.json)::

        {
          "mcpServers": {
            "context-router": {
              "command": "context-router",
              "args": ["mcp"]
            }
          }
        }
    """
    from mcp_server.main import main as _mcp_main
    _mcp_main()
