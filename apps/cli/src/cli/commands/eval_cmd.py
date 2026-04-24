"""`context-router eval` — Recall@K evaluation on queries.jsonl."""
from __future__ import annotations

from pathlib import Path

import typer
from evaluation.report import to_json, to_markdown
from evaluation.runner import EvalConfig, PackResult, run_evaluation

evaluation_app = typer.Typer(
    name="eval",
    help="Run Recall@K evaluation on a fixture.",
    invoke_without_command=True,
)


def _build_pack_real(q, project_root: Path, workspace_roots: list[Path]) -> PackResult:
    # Lazy import to keep --help fast.
    from core.orchestrator import Orchestrator

    orch = Orchestrator(project_root=project_root)
    pack = orch.build_pack(mode="implement", query=q.q)
    files = [item.path_or_ref for item in pack.selected_items if item.path_or_ref]
    tokens = sum(item.est_tokens for item in pack.selected_items)
    return PackResult(files=files, tokens=tokens)


@evaluation_app.callback(invoke_without_command=True)
def evaluation_main(
    queries: Path = typer.Option(..., "--queries", help="Path to queries.jsonl"),
    project_root: Path = typer.Option(Path("."), "--project-root"),
    k: int = typer.Option(20, "--k"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of markdown"),
):
    """Run the evaluation and emit a report to stdout."""
    cfg = EvalConfig(
        queries_path=queries,
        fixture_root=project_root,
        workspace_roots=[project_root],
        k=k,
    )
    report = run_evaluation(cfg, build_pack=_build_pack_real)
    typer.echo(to_json(report) if json_out else to_markdown(report))
