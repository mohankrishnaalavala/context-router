"""context-router explain command — explains the last generated context pack."""

from __future__ import annotations

import typer

explain_app = typer.Typer(help="Explain context selection decisions.")


@explain_app.command("last-pack")
def last_pack(
    json_output: bool = typer.Option(False, "--json", help="Output result as JSON."),
    show_call_chains: bool = typer.Option(
        False,
        "--show-call-chains",
        help="Show call chain relationships for each item.",
    ),
) -> None:
    """Print a human-readable rationale for the last generated context pack.

    Each selected item is shown with a one-sentence explanation of why it was
    included.  Run 'context-router pack' first to generate a pack.

    Use --show-call-chains to group and label call_chain items by their depth.

    Exit codes:
      0 — success
      1 — no pack found (run 'context-router pack' first)
    """
    from core.orchestrator import Orchestrator  # local import — keeps CLI startup fast

    result = Orchestrator().last_pack()

    if result is None:
        typer.echo(
            "No context pack found. Run 'context-router pack --mode <mode>' first.",
            err=True,
        )
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return

    typer.echo(
        f"Last pack  mode={result.mode}  items={len(result.selected_items)}  "
        f"tokens={result.total_est_tokens:,}"
    )
    typer.echo("")

    if show_call_chains:
        # Print non-call_chain items first, then call_chain items under a header
        main_items = [i for i in result.selected_items if i.source_type != "call_chain"]
        call_chain_items = [i for i in result.selected_items if i.source_type == "call_chain"]

        for item in main_items:
            typer.echo(f"  [{item.source_type}] {item.title}")
            typer.echo(f"    {item.reason}")

        if call_chain_items:
            typer.echo("")
            typer.echo("  --- Call chain items ---")
            for item in call_chain_items:
                typer.echo(f"  [call_chain] {item.title}")
                typer.echo(f"    {item.reason}")
    else:
        for item in result.selected_items:
            typer.echo(f"  [{item.source_type}] {item.title}")
            typer.echo(f"    {item.reason}")
