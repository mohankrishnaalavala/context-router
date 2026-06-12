"""context-router update-index command — single-file incremental index update.

Designed to be called from editor hooks (e.g. the Claude Code PostToolUse
hook installed by `context-router hooks install`) after every file edit.
Because a hook must NEVER break the user's editing session, every inactive
path exits 0 with a named stderr message instead of failing:

  * file outside the project root  → notice, exit 0
  * non-indexable extension        → notice, exit 0
  * missing index database         → WARN suggesting `context-router index`,
                                     exit 0
  * no project root discoverable   → WARN, exit 0

The heavy lifting reuses the watcher's per-file machinery: the indexer's
``run_incremental`` deletes existing rows for the file and re-analyzes it
(or just deletes them when the file was removed).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from contracts.config import load_config
from core.orchestrator import _find_project_root
from core.plugin_loader import PluginLoader
from graph_index.indexer import Indexer
from storage_sqlite.database import Database

update_index_app = typer.Typer(
    help="Incrementally update the index for a single edited file."
)


def _skip(message: str) -> None:
    """Emit a named skip reason to stderr and exit 0 (hook-safe)."""
    typer.echo(message, err=True)
    raise typer.Exit(code=0)


@update_index_app.callback(invoke_without_command=True)
def update_index(
    file: Annotated[
        Path,
        typer.Option(
            "--file",
            help="Path of the edited (or deleted) file to re-index.",
        ),
    ],
    project_root: Annotated[
        Optional[Path],
        typer.Option(
            "--project-root",
            "-p",
            help=(
                "Project root containing .context-router/. Auto-detected "
                "from the current directory when omitted."
            ),
        ),
    ] = None,
    repo_name: Annotated[
        str,
        typer.Option("--repo", help="Logical repository name stored with symbols."),
    ] = "default",
) -> None:
    """Update the index for a single file after an edit.

    Re-indexes FILE in place (delete old rows, re-analyze) or removes its
    rows if the file was deleted. Intended for editor hooks: every skip
    path is named on stderr and the command always exits 0 so it can never
    break an editing session.

    Exit codes:
      0 — always (success, skip, or recoverable failure; reason on stderr)
      2 — CLI usage error (e.g. missing --file)
    """
    file = file.resolve()

    if project_root is not None:
        root = project_root.resolve()
    else:
        try:
            root = _find_project_root(Path.cwd())
        except FileNotFoundError:
            _skip(
                "WARN: update-index skipped — no .context-router/ project "
                "found from the current directory. Run 'context-router init' "
                "then 'context-router index' to set one up."
            )

    try:
        file.relative_to(root)
    except ValueError:
        _skip(
            f"notice: update-index skipped — {file} is outside project "
            f"root {root}."
        )

    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        _skip(
            f"WARN: update-index skipped — index database not found at "
            f"{db_path}. Run 'context-router index' to build it."
        )

    try:
        config = load_config(root)
    except Exception as exc:  # noqa: BLE001 — hook-safe: never fail the edit
        _skip(f"WARN: update-index skipped — failed to load config: {exc}")

    plugin_loader = PluginLoader()
    plugin_loader.discover()

    ext = file.suffix.lstrip(".")
    if plugin_loader.get_analyzer(ext) is None:
        # Hooks fire on every edit, including docs — this path must be
        # cheap and quiet-but-named, never an error.
        _skip(
            f"notice: update-index skipped — no analyzer registered for "
            f"'.{ext}' files (non-indexable)."
        )

    db = Database(db_path)
    db.initialize()
    try:
        indexer = Indexer(db, plugin_loader, config, repo_name)
        # run_incremental handles both cases: existing file → delete old
        # rows + re-analyze; missing file → delete rows only.
        result = indexer.run_incremental([file])
    except Exception as exc:  # noqa: BLE001 — hook-safe: never fail the edit
        typer.echo(f"WARN: update-index failed for {file}: {exc}", err=True)
        raise typer.Exit(code=0) from exc
    finally:
        db.close()

    if result.errors:
        typer.echo(
            f"WARN: update-index completed with errors: {result.errors[0]}",
            err=True,
        )
    elif not file.is_file():
        typer.echo(f"[context-router] removed {file} from index", err=True)
    else:
        typer.echo(
            f"[context-router] updated index for {file} "
            f"({result.symbols_written} symbols)",
            err=True,
        )
