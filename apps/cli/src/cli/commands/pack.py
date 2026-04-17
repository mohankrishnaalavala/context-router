"""context-router pack command — generates a ranked context pack."""

from __future__ import annotations

from typing import Annotated

import typer

pack_app = typer.Typer(help="Generate a ranked context pack for a task.")

_VALID_MODES = ("review", "debug", "implement", "handover")


_VALID_FORMATS = ("json", "compact", "table")


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
        typer.Option("--json", help="Output result as JSON (equivalent to --format json)."),
    ] = False,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="Output format: table (default human-readable), json, or compact (path:title:excerpt lines).",
        ),
    ] = "table",
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
    page: Annotated[
        int,
        typer.Option("--page", help="Zero-based page index for paginated output (requires --page-size)."),
    ] = 0,
    page_size: Annotated[
        int,
        typer.Option("--page-size", help="Items per page. 0 = no pagination (return all items)."),
    ] = 0,
    use_embeddings: Annotated[
        bool,
        typer.Option(
            "--with-semantic/--no-semantic",
            help=(
                "Enable semantic ranking via all-MiniLM-L6-v2 "
                "(~33 MB download on first use)."
            ),
        ),
    ] = False,
    show_progress: Annotated[
        bool,
        typer.Option(
            "--progress/--no-progress",
            help="Show a progress bar for first-time model download.",
        ),
    ] = True,
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
        result = _run_build_pack(
            mode=mode,
            query=query,
            root=root,
            err_path=err_path,
            page=page,
            page_size=page_size,
            use_embeddings=use_embeddings,
            show_progress=show_progress,
        )
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    # --json flag takes precedence for backwards compatibility
    effective_format = "json" if json_output else format

    if effective_format == "json":
        typer.echo(result.model_dump_json(indent=2))
        return

    if effective_format == "compact":
        typer.echo(result.to_compact_text())
        return

    _print_pack(result)


def _run_build_pack(
    *,
    mode: str,
    query: str,
    root,  # Path | None
    err_path,  # Path | None
    page: int,
    page_size: int,
    use_embeddings: bool,
    show_progress: bool,
):
    """Call Orchestrator.build_pack with an optional rich progress bar.

    The progress bar is only rendered when:
    - ``--with-semantic`` is enabled, AND
    - ``--progress`` is on (default), AND
    - the sentence-transformers model is not yet cached on disk.

    Everything else goes through a silent path so interactive CLI usage
    stays quiet for cached packs and non-semantic mode.
    """
    from core.orchestrator import Orchestrator  # local import

    orch = Orchestrator(project_root=root)

    # Check cache eligibility cheaply: if the model is already cached we
    # skip the progress bar entirely. Non-semantic runs never show it.
    needs_progress = False
    if show_progress and use_embeddings:
        try:
            from ranking.ranker import _embed_model_is_cached
            needs_progress = not _embed_model_is_cached()
        except Exception:  # noqa: BLE001
            needs_progress = show_progress

    if not needs_progress:
        return orch.build_pack(
            mode,
            query,
            error_file=err_path,
            page=page,
            page_size=page_size,
            use_embeddings=use_embeddings,
            progress=False,
        )

    # First-time semantic run — wrap with rich progress.
    from rich.progress import (  # type: ignore[import-not-found]
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task_id = progress.add_task("Preparing semantic ranking…", total=None)

        def _cb(msg: str) -> None:
            progress.update(task_id, description=msg)

        return orch.build_pack(
            mode,
            query,
            error_file=err_path,
            page=page,
            page_size=page_size,
            use_embeddings=use_embeddings,
            progress=True,
            download_progress_cb=_cb,
        )


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
