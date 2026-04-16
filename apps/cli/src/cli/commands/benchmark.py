"""context-router benchmark command — runs the benchmark harness."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

benchmark_app = typer.Typer(help="Run the context-router benchmark harness.")


def _root_path(root: str) -> Path:
    return Path(root).resolve() if root else Path.cwd()


# ---------------------------------------------------------------------------
# benchmark run
# ---------------------------------------------------------------------------

@benchmark_app.command("run")
def benchmark_run(
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    output: Annotated[
        str,
        typer.Option("--output", "-o", help="Output JSON path. Auto-named when omitted."),
    ] = "",
    naive: Annotated[
        bool,
        typer.Option("--naive/--no-naive", help="Include naive baseline token count."),
    ] = True,
    keyword: Annotated[
        bool,
        typer.Option("--keyword/--no-keyword", help="Include keyword baseline token count."),
    ] = True,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    task_suite: Annotated[
        str,
        typer.Option(
            "--task-suite",
            help=(
                "Task suite to run: generic (default, Python/web), typescript, "
                "java, or dotnet."
            ),
        ),
    ] = "generic",
) -> None:
    """Run a benchmark task suite and produce a JSON + Markdown report.

    Exit codes:
      0 — success
      1 — project not initialised (no DB), or unknown --task-suite
    """
    from benchmark import BenchmarkRunner, to_json, to_markdown
    from benchmark.baselines import naive_tokens, keyword_tokens
    from benchmark.task_suite import get_task_suite

    root = _root_path(project_root)
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        typer.echo(
            "No index found. Run 'context-router init' and 'context-router index' first.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        tasks = get_task_suite(task_suite)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    if not json_output:
        typer.echo(f"Running {len(tasks)}-task '{task_suite}' benchmark suite...")
    runner = BenchmarkRunner(project_root=root)
    report = runner.run_suite(tasks=tasks)

    naive_tok = naive_tokens(root) if naive else 0
    keyword_tok = 0
    if keyword:
        # Use an implement-mode query as a representative sample
        keyword_tok = keyword_tokens(root, "implement feature endpoint handler")

    # Save JSON report
    cr_dir = root / ".context-router"
    cr_dir.mkdir(exist_ok=True)
    today = date.today().strftime("%Y%m%d")
    json_path = Path(output) if output else cr_dir / f"benchmark-{today}.json"
    json_path.write_text(to_json(report))

    # Save Markdown report alongside JSON
    md_path = json_path.with_suffix(".md")
    md_path.write_text(to_markdown(report, naive_tok=naive_tok, keyword_tok=keyword_tok))

    if json_output:
        typer.echo(to_json(report))
        return

    s = report.summary
    typer.echo(f"\n{'=' * 60}")
    typer.echo(f"Benchmark complete — run {report.run_id}")
    typer.echo(f"{'=' * 60}")
    typer.echo(f"  Tasks:           {s.get('total_tasks', 0)}")
    typer.echo(f"  Success rate:    {s.get('success_rate', 0):.1f}%")
    typer.echo(f"  Avg reduction:   {s.get('avg_reduction_pct', 0):.1f}%")
    typer.echo(f"  Avg tokens:      {s.get('avg_est_tokens', 0):,}")
    typer.echo(f"  Avg latency:     {s.get('avg_latency_ms', 0):.0f} ms")
    if naive_tok:
        router_tok = s.get("avg_est_tokens", 1) or 1
        vs_naive = round((naive_tok - router_tok) / naive_tok * 100, 1)
        typer.echo(f"  vs Naive:        -{vs_naive:.0f}% ({naive_tok:,} → {router_tok:,} tokens)")
    typer.echo(f"\nJSON report: {json_path}")
    typer.echo(f"Markdown:    {md_path}")


# ---------------------------------------------------------------------------
# benchmark report
# ---------------------------------------------------------------------------

@benchmark_app.command("report")
def benchmark_report(
    input_file: Annotated[
        str,
        typer.Option("--input", "-i", help="Path to benchmark JSON report file."),
    ] = "",
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root to auto-find latest report."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Print a Markdown summary of a saved benchmark JSON report.

    If --input is omitted, finds the most recent benchmark JSON in
    .context-router/.

    Exit codes:
      0 — success
      1 — no report found
    """
    from benchmark import to_json, to_markdown
    from benchmark.models import BenchmarkReport

    # Resolve report path
    if input_file:
        report_path = Path(input_file)
    else:
        root = _root_path(project_root)
        cr_dir = root / ".context-router"
        candidates = sorted(cr_dir.glob("benchmark-*.json"), reverse=True)
        if not candidates:
            typer.echo("No benchmark report found. Run 'context-router benchmark run' first.", err=True)
            raise typer.Exit(1)
        report_path = candidates[0]

    if not report_path.exists():
        typer.echo(f"Report not found: {report_path}", err=True)
        raise typer.Exit(1)

    report = BenchmarkReport.model_validate_json(report_path.read_text())

    if json_output:
        typer.echo(to_json(report))
    else:
        typer.echo(to_markdown(report))
