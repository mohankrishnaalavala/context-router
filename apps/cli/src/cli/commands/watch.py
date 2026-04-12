"""context-router watch command — watches for file changes and re-indexes.

Phase 1 stub.
"""

from __future__ import annotations

from typing import Annotated

import typer

watch_app = typer.Typer(help="Watch for file changes and incrementally re-index.")


@watch_app.callback(invoke_without_command=True)
def watch(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
) -> None:
    """Watch the current project for file changes and trigger incremental re-indexing.

    Phase 1 stub — watchdog integration not yet implemented.
    """
    typer.echo(
        "[Phase 1 stub] watch not yet implemented. "
        "Implement Phase 1 to enable file watching."
    )
