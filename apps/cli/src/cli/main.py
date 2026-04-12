"""context-router CLI — main entrypoint.

All commands are registered here. Business logic lives in the command
modules under cli/commands/ and in the core/storage packages — never here.
"""

from __future__ import annotations

import typer

from cli.commands.benchmark import benchmark_app
from cli.commands.decisions import decisions_app
from cli.commands.workspace import workspace_app
from cli.commands.explain import explain_app
from cli.commands.index import index_app
from cli.commands.init import init_app
from cli.commands.mcp import mcp_app
from cli.commands.memory import memory_app
from cli.commands.pack import pack_app
from cli.commands.watch import watch_app

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

app.add_typer(init_app, name="init")
app.add_typer(index_app, name="index")
app.add_typer(watch_app, name="watch")
app.add_typer(pack_app, name="pack")
app.add_typer(explain_app, name="explain")
app.add_typer(memory_app, name="memory")
app.add_typer(decisions_app, name="decisions")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(workspace_app, name="workspace")
app.add_typer(mcp_app, name="mcp")

if __name__ == "__main__":
    app()
