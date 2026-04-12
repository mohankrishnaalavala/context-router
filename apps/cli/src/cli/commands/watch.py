"""context-router watch command — watches for file changes and re-indexes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from contracts.config import load_config
from core.plugin_loader import PluginLoader
from graph_index.indexer import Indexer
from graph_index.watcher import IndexWatcher
from storage_sqlite.database import Database

watch_app = typer.Typer(help="Watch for file changes and incrementally re-index.")


@watch_app.callback(invoke_without_command=True)
def watch(
    project_root: Annotated[
        Path,
        typer.Option(
            "--project-root",
            "-p",
            help="Root of the project to watch. Defaults to current directory.",
        ),
    ] = Path("."),
    repo_name: Annotated[
        str,
        typer.Option("--repo", help="Logical repository name stored with symbols."),
    ] = "default",
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output initial index result as JSON."),
    ] = False,
) -> None:
    """Watch PROJECT_ROOT for file changes and trigger incremental re-indexing.

    Performs a full index on startup, then monitors the directory tree for
    changes. Modified or created files are re-indexed; deleted files are
    removed from the database.

    Press Ctrl-C to stop watching.

    Exit codes:
      0 — stopped cleanly (Ctrl-C)
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

            # Full index on startup
            typer.echo(f"Indexing {project_root} ...", err=True)
            result = indexer.run(project_root)

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
                    f"Initial index: {result.files_scanned} files, "
                    f"{result.symbols_written} symbols ({result.duration_seconds:.2f}s)",
                    err=True,
                )

            typer.echo(f"Watching {project_root} for changes ... (Ctrl-C to stop)", err=True)

            watcher = IndexWatcher(indexer, project_root, config)
            watcher.start()  # Blocks until KeyboardInterrupt

        finally:
            db.close()

    except typer.Exit:
        raise
    except KeyboardInterrupt:
        raise typer.Exit(code=0)
    except Exception as exc:  # noqa: BLE001
        _err(f"Unexpected error: {exc}", json_output, exit_code=2)


def _err(message: str, json_output: bool, exit_code: int) -> None:
    """Print an error to stderr and exit with the given code."""
    if json_output:
        typer.echo(json.dumps({"status": "error", "message": message}), err=True)
    else:
        typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=exit_code)
