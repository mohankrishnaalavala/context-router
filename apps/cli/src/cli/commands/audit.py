"""context-router audit command — surface quality / coverage gaps.

Currently implements ``--untested-hotspots``: ranks symbols that are in
the top N% of inbound ``calls``/``imports`` degree yet have zero
``tested_by`` edges.  This mirrors code-review-graph's
``get_knowledge_gaps`` tool, which became feasible here once
PR #48 landed ``tested_by`` edges for the context-router graph.

Design notes:
  * The subcommand is implemented as an ``invoke_without_command``
    callback so the registry's verify cmd
    ``context-router audit --untested-hotspots`` works as written.
  * ``--limit`` is the only tuning knob; no ``--hub-threshold`` flag —
    the interface is intentionally narrow per the outcome spec.
  * Silent failure is a bug: when the DB has zero ``tested_by`` edges
    the command emits a stderr warning explaining *why* no output is
    produced and exits 0.  Empty stdout is only allowed when the user
    can see the reason on stderr.
"""

from __future__ import annotations

import json as _json
import sys as _sys
from pathlib import Path
from typing import Annotated

import typer

audit_app = typer.Typer(
    help="Audit the index for quality / coverage gaps.",
    no_args_is_help=False,
)


def _find_project_root() -> Path:
    """Walk up from cwd to find a ``.context-router/`` directory.

    Raises:
        typer.BadParameter: If no ancestor contains ``.context-router/``.
    """
    current = Path.cwd().resolve()
    while True:
        if (current / ".context-router").is_dir():
            return current
        parent = current.parent
        if parent == current:
            raise typer.BadParameter(
                "No .context-router/ found. Run 'context-router init' first."
            )
        current = parent


@audit_app.callback(invoke_without_command=True)
def audit(
    ctx: typer.Context,
    untested_hotspots: Annotated[
        bool,
        typer.Option(
            "--untested-hotspots",
            help=(
                "Rank symbols in the top 10% of inbound degree that have "
                "zero tested_by edges (requires a v3 index)."
            ),
        ),
    ] = False,
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of rows to print (default 50)."),
    ] = 50,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of a human-readable table."),
    ] = False,
    repo_name: Annotated[
        str,
        typer.Option("--repo-name", help="Logical repository name (default: 'default')."),
    ] = "default",
) -> None:
    """Audit subcommand group.

    Without any flag this prints short usage help.  Today the only
    supported audit is ``--untested-hotspots``.
    """
    if ctx.invoked_subcommand is not None:
        # A nested audit subcommand (none today) was invoked — nothing for
        # the callback to do.
        return

    if not untested_hotspots:
        typer.echo(
            "Usage: context-router audit --untested-hotspots [--project-root PATH] "
            "[--limit N] [--json]",
            err=True,
        )
        raise typer.Exit(code=0)

    _run_untested_hotspots(
        project_root=project_root,
        limit=limit,
        json_out=json_out,
        repo_name=repo_name,
    )


def _run_untested_hotspots(
    project_root: str,
    limit: int,
    json_out: bool,
    repo_name: str,
) -> None:
    """Implementation of ``audit --untested-hotspots``.

    Split out so future audit flags can reuse the same DB-resolution path
    without growing the callback signature.
    """
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import EdgeRepository, SymbolRepository

    root = Path(project_root).resolve() if project_root else _find_project_root()
    db_path = root / ".context-router" / "context-router.db"

    if not db_path.exists():
        typer.echo(
            "No index found. Run 'context-router init' and 'context-router index' first.",
            err=True,
        )
        raise typer.Exit(code=1)

    # Clamp limit so callers can tune the output size without having to
    # think about the internal cap.
    if limit <= 0:
        limit = 50

    with Database(db_path) as db:
        edge_repo = EdgeRepository(db.connection)
        sym_repo = SymbolRepository(db.connection)

        # Silent-failure rule: if no tested_by edges exist at all, the
        # output would be misleading (every hot symbol looks "untested").
        # Warn on stderr and exit 0 with empty stdout — the user can act
        # on the advice to re-index.
        if edge_repo.count_by_type(repo_name, "tested_by") == 0:
            print(
                "No TESTED_BY edges indexed — run `context-router index` after "
                "updating to v3 to populate them.",
                file=_sys.stderr,
            )
            if json_out:
                typer.echo(_json.dumps({"items": []}))
            return

        hotspots = sym_repo.get_untested_hotspots(
            repo=repo_name,
            top_pct=0.10,
            limit_cap=limit,
        )

    if json_out:
        payload = {
            "items": [
                {
                    "symbol_id": ref.id,
                    "name": ref.name,
                    "kind": ref.kind,
                    "file": str(ref.file),
                    "language": ref.language,
                    "line": ref.line_start,
                    "inbound": inbound,
                    "reason": "untested",
                }
                for ref, inbound in hotspots
            ]
        }
        typer.echo(_json.dumps(payload))
        return

    # Human-readable output.
    typer.echo("Untested hotspots (top 10% by inbound degree, 0 TESTED_BY edges)")
    typer.echo("---")
    if not hotspots:
        # Surface the "why" on stderr so the empty stdout isn't silent.
        print(
            "No untested hotspots found — every hot symbol already has a "
            "tested_by edge.",
            file=_sys.stderr,
        )
        return

    for ref, inbound in hotspots:
        location = f"{ref.file.name}:{ref.line_start}" if ref.line_start else ref.file.name
        typer.echo(
            f"{ref.name} ({location})\tinbound={inbound}\treason: untested"
        )
