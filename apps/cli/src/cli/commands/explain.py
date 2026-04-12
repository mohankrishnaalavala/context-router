"""context-router explain command — explains the last generated context pack.

Phase 2 stub.
"""

from __future__ import annotations

import typer

explain_app = typer.Typer(help="Explain context selection decisions.")


@explain_app.command("last-pack")
def last_pack(
    json_output: bool = typer.Option(False, "--json", help="Output result as JSON."),
) -> None:
    """Print a human-readable rationale for the last generated context pack.

    Phase 2 stub — explain output not yet implemented.
    """
    typer.echo(
        "[Phase 2 stub] explain last-pack not yet implemented. "
        "Implement Phase 2 to enable selection explanation."
    )
