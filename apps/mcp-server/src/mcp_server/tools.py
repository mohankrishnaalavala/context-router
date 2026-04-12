"""MCP tool handlers for context-router.

Each function corresponds to one MCP tool.  All handlers are synchronous
(the stdio server calls them from an async context via asyncio.to_thread).
Input validation is intentionally lenient — unknown keys are ignored so
clients built against older schemas stay compatible.
"""

from __future__ import annotations

import json
from pathlib import Path


def _orchestrator(project_root: str = "") -> "Orchestrator":
    from core.orchestrator import Orchestrator
    root = Path(project_root) if project_root else None
    return Orchestrator(project_root=root)


# ---------------------------------------------------------------------------
# Index tools
# ---------------------------------------------------------------------------

def build_index(project_root: str = "", repo_name: str = "default") -> dict:
    """Full re-index of the repository.

    Args:
        project_root: Path to project root. Auto-detected if omitted.
        repo_name: Logical repository name.

    Returns:
        Dict with keys: files, symbols, edges, duration_seconds, errors.
    """
    from core.orchestrator import _find_project_root
    from contracts.config import load_config
    from core.plugin_loader import PluginLoader
    from graph_index.indexer import Indexer
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    config = load_config(root)
    db_path = root / ".context-router" / "context-router.db"

    if not db_path.exists():
        return {"error": f"Database not found at {db_path}. Run init first."}

    loader = PluginLoader()
    loader.discover()

    with Database(db_path) as db:
        indexer = Indexer(db, loader, config, repo_name)
        result = indexer.run(root)

    return {
        "files": result.files_scanned,
        "symbols": result.symbols_written,
        "edges": result.edges_written,
        "duration_seconds": round(result.duration_seconds, 3),
        "errors": result.errors[:10],  # cap at 10 to keep response small
    }


def update_index(
    changed_files: list[str],
    project_root: str = "",
    repo_name: str = "default",
) -> dict:
    """Incremental re-index for a list of changed files.

    Args:
        changed_files: List of file path strings (absolute or relative to cwd).
        project_root: Path to project root. Auto-detected if omitted.
        repo_name: Logical repository name.

    Returns:
        Dict with keys: files, symbols, edges, duration_seconds, errors.
    """
    from core.orchestrator import _find_project_root
    from contracts.config import load_config
    from core.plugin_loader import PluginLoader
    from graph_index.indexer import Indexer
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    config = load_config(root)
    db_path = root / ".context-router" / "context-router.db"

    if not db_path.exists():
        return {"error": f"Database not found at {db_path}. Run build_index first."}

    loader = PluginLoader()
    loader.discover()
    paths = [Path(f) for f in changed_files]

    with Database(db_path) as db:
        indexer = Indexer(db, loader, config, repo_name)
        result = indexer.run_incremental(paths)

    return {
        "files": result.files_scanned,
        "symbols": result.symbols_written,
        "edges": result.edges_written,
        "duration_seconds": round(result.duration_seconds, 3),
        "errors": result.errors[:10],
    }


# ---------------------------------------------------------------------------
# Pack tools
# ---------------------------------------------------------------------------

def get_context_pack(
    mode: str,
    query: str = "",
    project_root: str = "",
) -> dict:
    """Generate a ranked context pack.

    Args:
        mode: One of review|implement|debug|handover.
        query: Free-text task description.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Serialised ContextPack as a dict.
    """
    try:
        pack = _orchestrator(project_root).build_pack(mode, query)
        return pack.model_dump(mode="json")
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    except ValueError as exc:
        return {"error": str(exc)}


def get_debug_pack(
    query: str = "",
    error_file: str = "",
    project_root: str = "",
) -> dict:
    """Generate a debug-mode context pack, optionally parsing an error file.

    Args:
        query: Free-text description of the bug.
        error_file: Path to a JUnit XML, stack trace, or log file.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Serialised ContextPack as a dict.
    """
    err_path = Path(error_file) if error_file else None
    try:
        pack = _orchestrator(project_root).build_pack("debug", query, error_file=err_path)
        return pack.model_dump(mode="json")
    except FileNotFoundError as exc:
        return {"error": str(exc)}


def explain_selection(project_root: str = "") -> dict:
    """Return the explanation for the last generated context pack.

    Args:
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with mode, total_est_tokens, and per-item explanations.
    """
    pack = _orchestrator(project_root).last_pack()
    if pack is None:
        return {"error": "No pack found. Call get_context_pack first."}
    return {
        "mode": pack.mode,
        "query": pack.query,
        "total_est_tokens": pack.total_est_tokens,
        "baseline_est_tokens": pack.baseline_est_tokens,
        "reduction_pct": pack.reduction_pct,
        "items": [
            {
                "title": item.title,
                "source_type": item.source_type,
                "confidence": item.confidence,
                "reason": item.reason,
                "est_tokens": item.est_tokens,
            }
            for item in pack.selected_items
        ],
    }


def generate_handover(query: str = "", project_root: str = "") -> dict:
    """Generate a handover context pack combining memory + decisions + changes.

    Args:
        query: Optional task description for the handover.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Serialised ContextPack as a dict.
    """
    try:
        pack = _orchestrator(project_root).build_pack("handover", query)
        return pack.model_dump(mode="json")
    except FileNotFoundError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------

def search_memory(query: str, project_root: str = "") -> dict:
    """Full-text search stored observations.

    Args:
        query: FTS5 query string.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with a list of matching observation dicts.
    """
    from core.orchestrator import _find_project_root
    from memory.store import ObservationStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": "Database not found. Run init first.", "results": []}

    with Database(db_path) as db:
        store = ObservationStore(db)
        results = store.search(query)

    return {"results": [r.model_dump(mode="json") for r in results]}


def get_decisions(query: str = "", project_root: str = "") -> dict:
    """Search or list stored architectural decisions.

    Args:
        query: FTS5 query string. Returns all decisions when empty.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with a list of decision dicts.
    """
    from core.orchestrator import _find_project_root
    from memory.store import DecisionStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": "Database not found. Run init first.", "decisions": []}

    with Database(db_path) as db:
        store = DecisionStore(db)
        decisions = store.search(query) if query else store.get_all()

    return {"decisions": [d.model_dump(mode="json") for d in decisions]}
