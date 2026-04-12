"""context-router mcp command — starts the local MCP server.

Phase 5 stub.
"""

from __future__ import annotations

import typer

mcp_app = typer.Typer(help="Start the context-router MCP server.")


@mcp_app.callback(invoke_without_command=True)
def mcp(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Start the context-router MCP server over stdio transport.

    Phase 5 stub — MCP server not yet implemented.
    """
    typer.echo(
        "[Phase 5 stub] mcp not yet implemented. "
        "Implement Phase 5 to enable the MCP server."
    )
