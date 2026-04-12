"""context-router pack command — generates a ranked context pack."""

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
    project_root: Annotated[
        str,
        typer.Option(
            "--project-root",
            help="Project root containing .context-router/. Auto-detected when omitted.",
        ),
    ] = "",
    error_file: Annotated[
        str,
        typer.Option(
            "--error-file",
            "-e",
            help="Path to error file (JUnit XML, stack trace, log). Used in debug mode.",
        ),
    ] = "",
) -> None:
    """Generate a context pack for the given task MODE.

    Exit codes:
      0 — success
      1 — no index found (run 'context-router index' first)
      2 — invalid mode argument
    """
    if mode not in _VALID_MODES:
        typer.echo(
            f"Error: invalid mode '{mode}'. Must be one of: {', '.join(_VALID_MODES)}",
            err=True,
        )
        raise typer.Exit(code=2)

    from pathlib import Path

    from core.orchestrator import Orchestrator  # local import — keeps CLI startup fast

    root = Path(project_root) if project_root else None
    err_path = Path(error_file) if error_file else None
    try:
        result = Orchestrator(project_root=root).build_pack(mode, query, error_file=err_path)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return

    _print_pack(result)


def _print_pack(pack: object) -> None:  # type: ignore[type-arg]
    """Print a human-readable summary of a ContextPack."""
    from contracts.models import ContextPack  # local import

    assert isinstance(pack, ContextPack)

    typer.echo(
        f"Mode: {pack.mode}  |  "
        f"Items: {len(pack.selected_items)}  |  "
        f"Tokens: {pack.total_est_tokens:,} / {pack.baseline_est_tokens:,}  |  "
        f"Reduction: {pack.reduction_pct:.1f}%"
    )
    if pack.query:
        typer.echo(f"Query: {pack.query}")
    typer.echo("")

    col_widths = (40, 16, 10, 8)
    header = (
        f"{'Title':<{col_widths[0]}}  "
        f"{'Source':<{col_widths[1]}}  "
        f"{'Confidence':>{col_widths[2]}}  "
        f"{'Tokens':>{col_widths[3]}}"
    )
    typer.echo(header)
    typer.echo("-" * (sum(col_widths) + 6))

    for item in pack.selected_items:
        title = item.title[: col_widths[0] - 1] if len(item.title) >= col_widths[0] else item.title
        typer.echo(
            f"{title:<{col_widths[0]}}  "
            f"{item.source_type:<{col_widths[1]}}  "
            f"{item.confidence:>{col_widths[2]}.2f}  "
            f"{item.est_tokens:>{col_widths[3]},}"
        )
