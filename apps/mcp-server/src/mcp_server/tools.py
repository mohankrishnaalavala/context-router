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

    When an error_file is supplied and the pack contains items, an observation
    is automatically captured so the debug session is preserved in memory.

    Args:
        query: Free-text description of the bug.
        error_file: Path to a JUnit XML, stack trace, or log file.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Serialised ContextPack as a dict.
    """
    from core.orchestrator import _find_project_root
    err_path = Path(error_file) if error_file else None
    try:
        pack = _orchestrator(project_root).build_pack("debug", query, error_file=err_path)
    except FileNotFoundError as exc:
        return {"error": str(exc)}

    result = pack.model_dump(mode="json")

    # Auto-capture: save a lightweight debug observation when an error file was used
    if error_file and pack.selected_items:
        try:
            from contracts.models import Observation
            from memory.capture import capture_observation
            from memory.store import ObservationStore
            from storage_sqlite.database import Database

            root = Path(project_root) if project_root else _find_project_root(Path.cwd())
            db_path = root / ".context-router" / "context-router.db"
            if db_path.exists():
                files_from_pack = [
                    item.path_or_ref
                    for item in pack.selected_items
                    if item.path_or_ref
                ]
                obs = Observation(
                    task_type="debug",
                    summary=query or f"debug session: {Path(error_file).name}",
                    files_touched=files_from_pack[:20],
                )
                with Database(db_path) as db:
                    capture_observation(ObservationStore(db), obs, min_files=0)
        except Exception:  # noqa: BLE001
            pass  # auto-capture is best-effort; never fail the pack call

    return result


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

    A session-checkpoint observation is automatically captured each time a
    handover pack is generated so that the handover is preserved in memory.

    Args:
        query: Optional task description for the handover.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Serialised ContextPack as a dict.
    """
    from core.orchestrator import _find_project_root
    try:
        pack = _orchestrator(project_root).build_pack("handover", query)
    except FileNotFoundError as exc:
        return {"error": str(exc)}

    result = pack.model_dump(mode="json")

    # Auto-capture: save a handover checkpoint observation
    try:
        from contracts.models import Observation
        from memory.capture import capture_observation
        from memory.store import ObservationStore
        from storage_sqlite.database import Database

        root = Path(project_root) if project_root else _find_project_root(Path.cwd())
        db_path = root / ".context-router" / "context-router.db"
        if db_path.exists():
            files_from_pack = [
                item.path_or_ref
                for item in pack.selected_items
                if item.path_or_ref
            ]
            obs = Observation(
                task_type="handover",
                summary=query or "handover checkpoint",
                files_touched=files_from_pack[:20],
            )
            with Database(db_path) as db:
                capture_observation(ObservationStore(db), obs, min_files=0)
    except Exception:  # noqa: BLE001
        pass  # auto-capture is best-effort; never fail the pack call

    return result


# ---------------------------------------------------------------------------
# Memory tools
# ---------------------------------------------------------------------------

def save_observation(
    summary: str,
    task_type: str = "general",
    files_touched: "list[str] | None" = None,
    commands_run: "list[str] | None" = None,
    failures_seen: "list[str] | None" = None,
    fix_summary: str = "",
    commit_sha: str = "",
    project_root: str = "",
) -> dict:
    """Persist a coding-session observation to durable memory.

    Guardrails are applied automatically: duplicate observations (same
    task_type + summary) are silently skipped, and secret values in
    commands_run are redacted before storage.

    Args:
        summary: One-line description of the task or event (required).
        task_type: Category — e.g. debug, implement, commit, handover.
        files_touched: File paths modified during the task.
        commands_run: Shell commands executed (secrets will be redacted).
        failures_seen: Error/failure messages encountered.
        fix_summary: Short description of the resolution.
        commit_sha: Git commit SHA if available.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with ``saved`` bool and ``id`` (row ID) or ``reason`` when skipped.
    """
    from core.orchestrator import _find_project_root
    from contracts.models import Observation
    from memory.capture import capture_observation
    from memory.store import ObservationStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": "Database not found. Run init first.", "saved": False}

    obs = Observation(
        summary=summary,
        task_type=task_type,
        files_touched=files_touched or [],
        commands_run=commands_run or [],
        failures_seen=failures_seen or [],
        fix_summary=fix_summary,
        commit_sha=commit_sha,
    )

    with Database(db_path) as db:
        row_id = capture_observation(ObservationStore(db), obs, min_files=0)

    if row_id is None:
        return {"saved": False, "reason": "duplicate observation (same task_type + summary)"}
    return {"saved": True, "id": row_id}


def save_decision(
    title: str,
    decision: str,
    context: str = "",
    consequences: str = "",
    tags: "list[str] | None" = None,
    status: str = "accepted",
    project_root: str = "",
) -> dict:
    """Persist an architectural decision record (ADR) to project memory.

    Args:
        title: Short title for the decision (required).
        decision: The decision itself — what was chosen and why (required).
        context: Background context that motivated the decision.
        consequences: Trade-offs, risks, or follow-up actions.
        tags: List of tags for categorisation.
        status: One of proposed, accepted, deprecated, superseded.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with ``saved`` bool and ``id`` (UUID string).
    """
    from core.orchestrator import _find_project_root
    from contracts.models import Decision
    from memory.store import DecisionStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": "Database not found. Run init first.", "saved": False}

    dec = Decision(
        title=title,
        decision=decision,
        context=context,
        consequences=consequences,
        tags=tags or [],
        status=status,  # type: ignore[arg-type]
    )

    with Database(db_path) as db:
        decision_id = DecisionStore(db).add(dec)

    return {"saved": True, "id": decision_id}


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
