"""context-router benchmark command — runs the benchmark harness.

Phase 8 stub.
"""

from __future__ import annotations

import typer

benchmark_app = typer.Typer(help="Run the context-router benchmark harness.")


@benchmark_app.callback(invoke_without_command=True)
def benchmark(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run all benchmark tasks and produce a JSON report.

    Phase 8 stub — benchmark harness not yet implemented.
    """
    typer.echo(
        "[Phase 8 stub] benchmark not yet implemented. "
        "Implement Phase 8 to enable benchmarking."
    )
