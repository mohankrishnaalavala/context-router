"""context-router index command — scans and indexes a repository.

Phase 1 stub.
"""

from __future__ import annotations

from typing import Annotated

import typer

index_app = typer.Typer(help="Scan and index a repository's symbols and dependencies.")


@index_app.callback(invoke_without_command=True)
def index(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
) -> None:
    """Index the current project's source files into the context-router database.

    Phase 1 stub — file scanning and symbol extraction not yet implemented.
    """
    typer.echo(
        "[Phase 1 stub] index not yet implemented. "
        "Implement Phase 1 to enable repository indexing."
    )
