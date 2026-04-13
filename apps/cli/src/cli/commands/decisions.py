"""context-router decisions command — manages architectural decision records."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

decisions_app = typer.Typer(help="Manage architectural decision records (ADRs).")


def _open_store(project_root: str) -> tuple["DecisionStore", "Database"]:
    """Open the database and return (DecisionStore, Database).

    Caller must close the Database.
    """
    from core.orchestrator import _find_project_root
    from memory.store import DecisionStore
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
    return DecisionStore(db), db


@decisions_app.command("add")
def add(
    title: Annotated[str, typer.Argument(help="Short title for the decision.")],
    context: Annotated[
        str,
        typer.Option("--context", "-c", help="Background context for the decision."),
    ] = "",
    decision: Annotated[
        str,
        typer.Option("--decision", "-d", help="The decision that was made."),
    ] = "",
    consequences: Annotated[
        str,
        typer.Option("--consequences", help="Consequences and trade-offs."),
    ] = "",
    tags: Annotated[
        str,
        typer.Option("--tags", help="Comma-separated tags (e.g. storage,performance)."),
    ] = "",
    status: Annotated[
        str,
        typer.Option("--status", help="proposed|accepted|deprecated|superseded"),
    ] = "accepted",
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Add a new architectural decision record.

    Exit codes:
      0 — success
      1 — database not initialised
      2 — invalid status value
    """
    valid_statuses = ("proposed", "accepted", "deprecated", "superseded")
    if status not in valid_statuses:
        typer.echo(f"Error: --status must be one of: {', '.join(valid_statuses)}", err=True)
        raise typer.Exit(2)

    from contracts.models import Decision

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    dec = Decision(
        title=title,
        status=status,  # type: ignore[arg-type]
        context=context,
        decision=decision,
        consequences=consequences,
        tags=tag_list,
    )

    store, db = _open_store(project_root)
    try:
        dec_id = store.add(dec)
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps({"id": dec_id, "title": title}))
    else:
        typer.echo(f"Decision added: {dec_id[:8]}  {title}")


@decisions_app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Search stored architectural decisions by keyword.

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
        typer.echo("No decisions found.")
        return

    for dec in results:
        typer.echo(f"  [{dec.status}] {dec.title}")
        if dec.decision:
            typer.echo(f"    {dec.decision[:120]}")
        if dec.tags:
            typer.echo(f"    tags: {', '.join(dec.tags)}")


@decisions_app.command("list")
def list_decisions(
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List all stored architectural decisions.

    Exit codes:
      0 — success
      1 — database not initialised
    """
    store, db = _open_store(project_root)
    try:
        all_decs = store.get_all()
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps([d.model_dump(mode="json") for d in all_decs], indent=2))
        return

    if not all_decs:
        typer.echo("No decisions stored yet.")
        return

    for dec in all_decs:
        typer.echo(f"  [{dec.status}] {dec.title}")


@decisions_app.command("supersede")
def supersede(
    old_id: Annotated[str, typer.Argument(help="UUID of the decision being replaced.")],
    new_id: Annotated[str, typer.Argument(help="UUID of the new decision that supersedes it.")],
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Mark an old decision as superseded by a newer one.

    Sets the old decision's status to 'superseded' and records the link
    to the new decision UUID.

    Exit codes:
      0 — success
      1 — database not initialised
    """
    store, db = _open_store(project_root)
    try:
        store.mark_superseded(old_id, new_id)
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps({"superseded": old_id, "superseded_by": new_id}))
    else:
        typer.echo(f"Decision {old_id[:8]} marked as superseded by {new_id[:8]}.")
