"""context-router feedback command — records agent feedback for context packs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

feedback_app = typer.Typer(help="Record and review agent feedback for context packs.")


def _open_store(project_root: str) -> tuple["FeedbackStore", "Database"]:
    """Open the database and return (FeedbackStore, Database)."""
    from core.orchestrator import _find_project_root
    from memory.store import FeedbackStore
    from storage_sqlite.database import Database

    root = (
        Path(project_root).resolve()
        if project_root
        else _find_project_root(Path.cwd()).resolve()
    )
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        typer.echo(
            "No index found. Run 'context-router init' and 'context-router index' first.",
            err=True,
        )
        raise typer.Exit(1)
    db = Database(db_path)
    db.initialize()
    return FeedbackStore(db, repo_scope=str(root)), db


@feedback_app.command("record")
def record(
    pack_id: Annotated[str, typer.Option("--pack-id", help="UUID of the context pack.")],
    useful: Annotated[
        str,
        typer.Option("--useful", help="Was the pack useful? yes / no"),
    ] = "",
    missing: Annotated[
        str,
        typer.Option("--missing", help="Space-separated file/symbol paths that were needed but absent."),
    ] = "",
    noisy: Annotated[
        str,
        typer.Option("--noisy", help="Space-separated file/symbol paths that were irrelevant."),
    ] = "",
    too_much_context: Annotated[
        bool,
        typer.Option("--too-much-context", help="Flag if the pack contained too much context."),
    ] = False,
    reason: Annotated[
        str,
        typer.Option("--reason", help="Free-text explanation."),
    ] = "",
    files_read: Annotated[
        str,
        typer.Option("--files-read", help="Space-separated file paths the agent actually consumed."),
    ] = "",
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Record agent feedback for a context pack.

    Feedback is used to improve future pack rankings: files reported as missing
    get a confidence boost, files reported as noisy get a confidence penalty
    (applied after ≥ 3 occurrences to avoid single-report noise).

    Example::

        context-router feedback record --pack-id PACK_UUID --useful yes
        context-router feedback record --pack-id PACK_UUID --useful no \\
          --missing "auth.py" --noisy "tests/conftest.py" --reason "auth missing"

    Exit codes:
      0 — success
      1 — database not initialised
    """
    from contracts.models import PackFeedback

    useful_bool: bool | None = None
    if useful.lower() in ("yes", "true", "1"):
        useful_bool = True
    elif useful.lower() in ("no", "false", "0"):
        useful_bool = False

    missing_list = [f for f in missing.split() if f] if missing else []
    noisy_list = [f for f in noisy.split() if f] if noisy else []
    files_read_list = [f for f in files_read.split() if f] if files_read else []

    fb = PackFeedback(
        pack_id=pack_id,
        useful=useful_bool,
        missing=missing_list,
        noisy=noisy_list,
        too_much_context=too_much_context,
        reason=reason,
        files_read=files_read_list,
    )

    store, db = _open_store(project_root)
    try:
        fb_id = store.add(fb)
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps({"recorded": True, "id": fb_id}))
    else:
        typer.echo(f"Feedback recorded: {fb_id[:8]}")


@feedback_app.command("stats")
def stats(
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show aggregate feedback statistics.

    Reports the overall usefulness percentage and the top missing/noisy files.

    Exit codes:
      0 — success
      1 — database not initialised
    """
    store, db = _open_store(project_root)
    try:
        result = store.aggregate_stats()
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps(result))
        return

    total = result["total"]
    if total == 0:
        typer.echo("No feedback recorded yet.")
        return

    typer.echo(f"Total feedback: {total}")
    typer.echo(f"  Useful: {result['useful_count']}  Not useful: {result['not_useful_count']}  ({result['useful_pct']}%)")
    if result["top_missing"]:
        typer.echo("  Top missing files:")
        for path in result["top_missing"]:
            typer.echo(f"    {path}")
    if result["top_noisy"]:
        typer.echo("  Top noisy files:")
        for path in result["top_noisy"]:
            typer.echo(f"    {path}")
    if "read_overlap_pct" in result:
        typer.echo(
            f"  Read coverage ({result['reports_with_files_read']} reports): "
            f"{result['read_overlap_pct']}% useful reads  |  "
            f"{result['noise_ratio_pct']}% noise ratio"
        )


@feedback_app.command("list")
def list_feedback(
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of feedback records to show."),
    ] = 20,
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List recent feedback records.

    Exit codes:
      0 — success
      1 — database not initialised
    """
    store, db = _open_store(project_root)
    try:
        records = store.get_all(limit)
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps([r.model_dump(mode="json") for r in records], indent=2))
        return

    if not records:
        typer.echo("No feedback recorded yet.")
        return

    for fb in records:
        useful_str = {True: "yes", False: "no", None: "—"}.get(fb.useful, "—")
        typer.echo(f"  [{fb.pack_id[:8]}] useful={useful_str}  missing={len(fb.missing)}  noisy={len(fb.noisy)}")
        if fb.reason:
            typer.echo(f"    {fb.reason}")
