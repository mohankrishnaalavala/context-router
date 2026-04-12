"""context-router init command — bootstraps a project's .context-router directory and SQLite DB."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from contracts.config import DEFAULT_CONFIG_YAML
from storage_sqlite.database import Database

init_app = typer.Typer(help="Initialize context-router in the current project.")


@init_app.callback(invoke_without_command=True)
def init(
    project_root: Annotated[
        Path,
        typer.Option(
            "--project-root",
            "-p",
            help="Root of the project to initialize. Defaults to current directory.",
            exists=False,
        ),
    ] = Path("."),
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON."),
    ] = False,
) -> None:
    """Bootstrap .context-router/ and the SQLite database in PROJECT_ROOT.

    Creates:
      - .context-router/config.yaml  (default config, if not already present)
      - .context-router/context-router.db  (SQLite database with full schema)

    Exit codes:
      0 — success
      1 — user error (bad path, permission denied)
      2 — internal error (unexpected failure)
    """
    try:
        project_root = project_root.resolve()
        config_dir = project_root / ".context-router"

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            _err(f"Cannot create {config_dir}: {exc}", json_output, exit_code=1)
            return

        config_yaml = config_dir / "config.yaml"
        if not config_yaml.exists():
            config_yaml.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")

        db_path = config_dir / "context-router.db"
        db = Database(db_path)
        db.initialize()
        db.close()

        if json_output:
            typer.echo(json.dumps({"status": "ok", "db_path": str(db_path)}))
        else:
            typer.echo(f"Initialized context-router in {config_dir}")

    except Exception as exc:  # noqa: BLE001
        _err(f"Unexpected error: {exc}", json_output, exit_code=2)


def _err(message: str, json_output: bool, exit_code: int) -> None:
    """Print an error to stderr and exit with the given code."""
    if json_output:
        typer.echo(json.dumps({"status": "error", "message": message}), err=True)
    else:
        typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=exit_code)
