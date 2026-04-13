"""context-router memory command — manages durable session observations."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

memory_app = typer.Typer(help="Manage durable session memory (observations).")


def _open_store(project_root: str) -> tuple["ObservationStore", "Database"]:
    """Open the database and return (ObservationStore, Database).

    Caller must close the Database.
    """
    from core.orchestrator import _find_project_root
    from memory.store import ObservationStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        typer.echo(
            "No index found. Run 'context-router init' and 'context-router index' first.",
            err=True,
        )
        raise typer.Exit(1)
    db = Database(db_path)
    db.initialize()
    return ObservationStore(db), db


@memory_app.command("add")
def add(
    from_session: Annotated[
        str,
        typer.Option("--from-session", help="Path to session JSON file."),
    ] = "",
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Read session JSON from stdin instead of a file."),
    ] = False,
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Add observations from a session JSON file or stdin to durable memory.

    Provide exactly one of --from-session PATH or --stdin.  The input must be
    a JSON object or array matching the Observation schema (summary field is
    required; all others are optional).

    Exit codes:
      0 — success
      1 — file not found, database not initialised, or no input source given
      2 — invalid JSON or schema
    """
    if stdin:
        session_json = sys.stdin.read()
    elif from_session:
        session_path = Path(from_session)
        if not session_path.exists():
            typer.echo(f"Session file not found: {from_session}", err=True)
            raise typer.Exit(1)
        session_json = session_path.read_text(encoding="utf-8")
    else:
        typer.echo("Provide --from-session PATH or --stdin.", err=True)
        raise typer.Exit(1)

    store, db = _open_store(project_root)
    try:
        ids = store.add_from_session_json(session_json)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2)
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps({"added": len(ids), "ids": ids}))
    else:
        typer.echo(f"Added {len(ids)} observation(s) to memory.")


@memory_app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Search stored observations by keyword.

    Exit codes:
      0 — success (even if no results)
      1 — database not initialised
    """
    store, db = _open_store(project_root)
    try:
        results = store.search(query)
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
        return

    if not results:
        typer.echo("No observations found.")
        return

    for obs in results:
        typer.echo(f"  [{obs.task_type or 'general'}] {obs.summary}")
        if obs.fix_summary:
            typer.echo(f"    Fix: {obs.fix_summary}")


@memory_app.command("stale")
def stale(
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List observations that reference files no longer in the index.

    Exit codes:
      0 — success (even if no stale observations)
      1 — database not initialised
    """
    store, db = _open_store(project_root)
    try:
        stale_obs = store.find_stale()
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps([o.model_dump(mode="json") for o in stale_obs], indent=2))
        return

    if not stale_obs:
        typer.echo("No stale observations found.")
        return

    typer.echo(f"{len(stale_obs)} stale observation(s) (files no longer indexed):")
    for obs in stale_obs:
        typer.echo(f"  {obs.summary[:80]}")


@memory_app.command("capture")
def capture(
    summary: Annotated[str, typer.Argument(help="One-line task summary.")],
    task_type: Annotated[
        str,
        typer.Option("--task-type", help="Task type (e.g. debug, implement, commit, handover)."),
    ] = "general",
    files: Annotated[
        str,
        typer.Option("--files", help="Space-separated file paths touched during the task."),
    ] = "",
    commit: Annotated[
        str,
        typer.Option("--commit", help="Git commit SHA associated with this observation."),
    ] = "",
    fix: Annotated[
        str,
        typer.Option("--fix", help="Short description of the fix or resolution."),
    ] = "",
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Capture a task observation directly from command-line arguments.

    Unlike 'memory add' which imports a JSON file, 'capture' lets adapters
    and hooks persist a normalized observation in one command.  Guardrails
    are applied: duplicate tasks (same type + summary) are silently skipped,
    and secret values in --files are not exposed.

    Example::

        context-router memory capture "fixed auth bug" \\
          --task-type debug --files "auth.py tests/test_auth.py" \\
          --commit abc1234 --fix "added null-check on token"

    Exit codes:
      0 — success (or silently skipped duplicate)
      1 — database not initialised
    """
    from contracts.models import Observation
    from memory.capture import capture_observation

    files_list = [f for f in files.split() if f] if files else []

    obs = Observation(
        summary=summary,
        task_type=task_type,
        files_touched=files_list,
        commit_sha=commit,
        fix_summary=fix,
    )

    store, db = _open_store(project_root)
    try:
        row_id = capture_observation(store, obs, min_files=0)
    finally:
        db.close()

    if json_output:
        import json
        if row_id is None:
            typer.echo(json.dumps({"captured": False, "reason": "duplicate"}))
        else:
            typer.echo(json.dumps({"captured": True, "id": row_id}))
    else:
        if row_id is None:
            typer.echo("Skipped: duplicate observation (same task type + summary).")
        else:
            typer.echo(f"Captured observation #{row_id}.")
