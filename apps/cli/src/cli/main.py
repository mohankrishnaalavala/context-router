"""context-router CLI — main entrypoint.

All commands are registered here. Business logic lives in the command
modules under cli/commands/ and in the core/storage packages — never here.
"""

from __future__ import annotations

from importlib import metadata

import typer

from cli.commands.audit import audit_app
from cli.commands.benchmark import benchmark_app
from cli.commands.decisions import decisions_app
from cli.commands.embed import embed_app
from cli.commands.explain import explain_app
from cli.commands.feedback import feedback_app
from cli.commands.graph import graph_app
from cli.commands.index import index_app
from cli.commands.init import init_app
from cli.commands.mcp import mcp_app
from cli.commands.memory import memory_app
from cli.commands.pack import pack_app
from cli.commands.setup import setup_app
from cli.commands.watch import watch_app
from cli.commands.workspace import workspace_app

_DIST_NAME = "context-router-cli"


def _resolve_version() -> str:
    """Return the installed distribution version.

    Raises ``RuntimeError`` if the package metadata is missing — this would
    only happen in a broken install, and silent failure is a bug per
    CLAUDE.md's quality gate.
    """
    try:
        return metadata.version(_DIST_NAME)
    except metadata.PackageNotFoundError as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"could not determine version: distribution '{_DIST_NAME}' "
            "is not installed. Reinstall the package."
        ) from exc


def _version_callback(value: bool) -> None:
    """Typer eager callback: print version and exit 0."""
    if not value:
        return
    typer.echo(f"context-router {_resolve_version()}")
    raise typer.Exit(code=0)


app = typer.Typer(
    name="context-router",
    help=(
        "Local-first context selector for AI coding agents.\n\n"
        "Selects the minimum useful context across code structure, "
        "runtime evidence, and project memory for review, debug, "
        "implement, and handover tasks."
    ),
    no_args_is_help=True,
)


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the installed version and exit.",
        is_eager=True,
        callback=_version_callback,
    ),
) -> None:
    """Root callback — hosts the global ``--version`` flag."""
    # Nothing to do here: subcommands handle their own work, and the
    # version callback exits before this body runs.
    return

app.add_typer(init_app, name="init")
app.add_typer(index_app, name="index")
app.add_typer(watch_app, name="watch")
app.add_typer(embed_app, name="embed")
app.add_typer(pack_app, name="pack")
app.add_typer(explain_app, name="explain")
app.add_typer(memory_app, name="memory")
app.add_typer(decisions_app, name="decisions")
app.add_typer(feedback_app, name="feedback")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(workspace_app, name="workspace")
app.add_typer(setup_app, name="setup")
app.add_typer(mcp_app, name="mcp")
app.add_typer(graph_app, name="graph")
app.add_typer(audit_app, name="audit")

if __name__ == "__main__":
    app()
