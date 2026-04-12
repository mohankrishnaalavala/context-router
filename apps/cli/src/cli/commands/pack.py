"""context-router pack command — generates a ranked context pack.

Phase 2 stub: validates mode, then prints a not-implemented message.
"""

from __future__ import annotations

from typing import Annotated

import typer

pack_app = typer.Typer(help="Generate a ranked context pack for a task.")

_VALID_MODES = ("review", "debug", "implement", "handover")


@pack_app.callback(invoke_without_command=True)
def pack(
    mode: Annotated[
        str,
        typer.Option("--mode", "-m", help="Task mode: review|debug|implement|handover."),
    ],
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Free-text description of the task."),
    ] = "",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
) -> None:
    """Generate a context pack for the given task MODE.

    Phase 2 stub — ranking and pack assembly not yet implemented.

    Exit codes:
      0 — success (stub)
      2 — invalid mode argument
    """
    if mode not in _VALID_MODES:
        typer.echo(
            f"Error: invalid mode '{mode}'. Must be one of: {', '.join(_VALID_MODES)}",
            err=True,
        )
        raise typer.Exit(code=2)

    typer.echo(
        f"[Phase 2 stub] pack --mode {mode} not yet implemented. "
        "Implement Phase 2 to enable context pack generation."
    )
