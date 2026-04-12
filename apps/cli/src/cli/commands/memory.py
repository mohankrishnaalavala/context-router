"""context-router memory command — manages durable session observations.

Phase 4 stub.
"""

from __future__ import annotations

import typer

memory_app = typer.Typer(help="Manage durable session memory (observations).")


@memory_app.command("add")
def add(
    from_session: str = typer.Option(..., "--from-session", help="Path to session JSON file."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Add observations from a session JSON file to durable memory.

    Phase 4 stub — memory ingestion not yet implemented.
    """
    typer.echo(
        "[Phase 4 stub] memory add not yet implemented. "
        "Implement Phase 4 to enable memory storage."
    )
