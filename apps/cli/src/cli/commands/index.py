"""context-router index command — scans and indexes a repository."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from contracts.config import load_config
from core.plugin_loader import PluginLoader
from graph_index.git_diff import GitDiffParser
from graph_index.indexer import Indexer
from storage_sqlite.database import Database

index_app = typer.Typer(help="Scan and index a repository's symbols and dependencies.")


@index_app.callback(invoke_without_command=True)
def index(
    project_root: Annotated[
        Path,
        typer.Option(
            "--project-root",
            "-p",
            help="Root of the project to index. Defaults to current directory.",
        ),
    ] = Path("."),
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Git ref for incremental index (e.g. HEAD~1, a1b2c3d).",
        ),
    ] = None,
    repo_name: Annotated[
        str,
        typer.Option("--repo", help="Logical repository name stored with symbols."),
    ] = "default",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
) -> None:
    """Index source files into the context-router database.

    Scans PROJECT_ROOT for source files, runs language analyzers, and writes
    symbols and dependency edges to the SQLite database.

    For incremental indexing pass --since <git-ref> to re-index only files
    that changed since that ref.

    Exit codes:
      0 — success (even with per-file errors)
      1 — configuration / setup error
      2 — unexpected internal error
    """
    try:
        project_root = project_root.resolve()
        config_dir = project_root / ".context-router"

        try:
            config = load_config(project_root)
        except Exception as exc:  # noqa: BLE001
            _err(f"Failed to load config: {exc}", json_output, exit_code=1)
            return

        db_path = config_dir / "context-router.db"
        if not db_path.exists():
            _err(
                f"Database not found at {db_path}. Run 'context-router init' first.",
                json_output,
                exit_code=1,
            )
            return

        db = Database(db_path)
        db.initialize()

        try:
            plugin_loader = PluginLoader()
            plugin_loader.discover()

            indexer = Indexer(db, plugin_loader, config, repo_name)

            if since is not None:
                try:
                    diff = GitDiffParser.from_git(project_root, since)
                    changed = [
                        cf.path if cf.path.is_absolute() else project_root / cf.path
                        for cf in diff
                        if cf.status != "deleted"
                    ]
                    # Also include deleted files so the indexer can clean them up
                    deleted = [
                        cf.path if cf.path.is_absolute() else project_root / cf.path
                        for cf in diff
                        if cf.status == "deleted"
                    ]
                    result = indexer.run_incremental(changed + deleted)
                except Exception as exc:  # noqa: BLE001
                    _err(f"Git diff failed: {exc}", json_output, exit_code=1)
                    return
            else:
                result = indexer.run(project_root)
        finally:
            db.close()

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "files_scanned": result.files_scanned,
                        "symbols_written": result.symbols_written,
                        "edges_written": result.edges_written,
                        "duration_seconds": round(result.duration_seconds, 3),
                        "errors": result.errors,
                    }
                )
            )
        else:
            typer.echo(
                f"Indexed {result.files_scanned} files — "
                f"{result.symbols_written} symbols, {result.edges_written} edges "
                f"({result.duration_seconds:.2f}s)"
            )
            if result.errors:
                typer.echo(f"  {len(result.errors)} file(s) had errors:", err=True)
                for err in result.errors[:10]:
                    typer.echo(f"    {err}", err=True)
                if len(result.errors) > 10:
                    typer.echo(
                        f"    ... and {len(result.errors) - 10} more", err=True
                    )

    except Exception as exc:  # noqa: BLE001
        _err(f"Unexpected error: {exc}", json_output, exit_code=2)


def _err(message: str, json_output: bool, exit_code: int) -> None:
    """Print an error to stderr and exit with the given code."""
    if json_output:
        typer.echo(json.dumps({"status": "error", "message": message}), err=True)
    else:
        typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=exit_code)
