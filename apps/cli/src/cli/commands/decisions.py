"""context-router decisions command — manages architectural decision records.

Phase 4 stub.
"""

from __future__ import annotations

import typer

decisions_app = typer.Typer(help="Manage architectural decision records (ADRs).")


@decisions_app.command("add")
def add(
    title: str = typer.Argument(..., help="Short title for the decision."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Add a new architectural decision record.

    Phase 4 stub — decision storage not yet implemented.
    """
    typer.echo(
        "[Phase 4 stub] decisions add not yet implemented. "
        "Implement Phase 4 to enable decision storage."
    )


@decisions_app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Search stored architectural decisions by keyword.

    Phase 4 stub — decision search not yet implemented.
    """
    typer.echo(
        "[Phase 4 stub] decisions search not yet implemented. "
        "Implement Phase 4 to enable decision search."
    )
