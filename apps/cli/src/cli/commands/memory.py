"""context-router memory command — manages durable session observations."""

from __future__ import annotations

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
    ],
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Add observations from a session JSON file to durable memory.

    The session file must be a JSON object or array matching the Observation
    schema (summary field is required; all others are optional).

    Exit codes:
      0 — success
      1 — file not found or database not initialised
      2 — invalid JSON or schema
    """
    session_path = Path(from_session)
    if not session_path.exists():
        typer.echo(f"Session file not found: {from_session}", err=True)
        raise typer.Exit(1)

    store, db = _open_store(project_root)
    try:
        ids = store.add_from_session_json(session_path.read_text(encoding="utf-8"))
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
