"""MCP tool handlers for context-router.

Each function corresponds to one MCP tool.  All handlers are synchronous
(the stdio server calls them from an async context via asyncio.to_thread).
Input validation is intentionally lenient — unknown keys are ignored so
clients built against older schemas stay compatible.
"""

from __future__ import annotations

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
    from contracts.config import load_config
    from core.orchestrator import _find_project_root
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
    from contracts.config import load_config
    from core.orchestrator import _find_project_root
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
    format: str = "json",
    page: int = 0,
    page_size: int = 0,
    progress_cb=None,
) -> dict:
    """Generate a ranked context pack.

    Args:
        mode: One of review|implement|debug|handover.
        query: Free-text task description.
        project_root: Project root. Auto-detected if omitted.
        format: Output format — "json" (default, full serialisation) or "compact"
            (path:title:excerpt lines, lower token overhead for agent consumption).
        page: Zero-based page index (used with page_size for incremental loading).
        page_size: Items per page. 0 = no pagination (return all ranked items).
        progress_cb: Optional ``(stage, progress, total)`` callable invoked at
            build milestones.  Supplied by the MCP dispatcher when the caller
            sends a ``progressToken``; normal CLI callers leave this ``None``.

    Returns:
        Serialised ContextPack as a dict, or {"text": ...} when format="compact".
    """
    try:
        pack = _orchestrator(project_root).build_pack(
            mode, query, page=page, page_size=page_size, progress_cb=progress_cb,
        )
        if format == "compact":
            return {"text": pack.to_compact_text(), "has_more": pack.has_more, "total_items": pack.total_items}
        return pack.model_dump(mode="json")
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    except ValueError as exc:
        return {"error": str(exc)}


def get_context_summary(
    mode: str,
    query: str = "",
    project_root: str = "",
) -> dict:
    """Return a lightweight summary of a context pack (< 200 tokens).

    Use this before get_context_pack to decide whether you need the full pack.
    Returns item count, token total, reduction %, top 5 files, and source type
    distribution without sending all item details.

    Args:
        mode: One of review|implement|debug|handover.
        query: Free-text task description.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with mode, item_count, total_est_tokens, reduction_pct, top_files,
        source_type_counts.
    """
    from collections import Counter
    try:
        pack = _orchestrator(project_root).build_pack(mode, query)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    except ValueError as exc:
        return {"error": str(exc)}

    source_counts = Counter(i.source_type for i in pack.selected_items)
    top_files = sorted(pack.selected_items, key=lambda i: i.confidence, reverse=True)[:5]
    return {
        "mode": pack.mode,
        "query": pack.query,
        "item_count": len(pack.selected_items),
        "total_est_tokens": pack.total_est_tokens,
        "baseline_est_tokens": pack.baseline_est_tokens,
        "reduction_pct": round(pack.reduction_pct, 1),
        "top_files": [
            {"path": i.path_or_ref, "title": i.title, "confidence": round(i.confidence, 2)}
            for i in top_files
        ],
        "source_type_counts": dict(source_counts.most_common(5)),
    }


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


def suggest_next_files(
    pack_id: str = "",
    project_root: str = "",
    limit: int = 3,
) -> dict:
    """Given the last context pack, suggest the top N files to read next.

    Uses structural adjacency of items in the pack (imports and callers),
    ranked by how many pack items reference each candidate.  Files already
    in the pack are excluded.

    Args:
        pack_id: UUID of the pack (uses last pack if omitted).
        project_root: Project root. Auto-detected if omitted.
        limit: Maximum number of files to return (default 3).

    Returns:
        Dict with ``suggestions`` list of {file, reason} dicts.
    """
    from core.orchestrator import _find_project_root

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": "Database not found. Run init first.", "suggestions": []}

    # Retrieve the pack whose items we will use as the starting set.
    try:
        from core.orchestrator import Orchestrator
        orch = Orchestrator(project_root=root)

        if pack_id:
            # Try to load by pack_id via the storage layer
            try:
                from contracts.models import ContextPack
                from storage_sqlite.database import Database
                with Database(db_path) as db:
                    row = db.connection.execute(
                        "SELECT payload FROM context_packs WHERE id = ?", (pack_id,)
                    ).fetchone()
                if row is None:
                    return {"error": f"Pack {pack_id!r} not found.", "suggestions": []}
                import json as _json
                pack = ContextPack.model_validate(_json.loads(row["payload"]))
            except Exception:  # noqa: BLE001
                pack = orch.last_pack()
        else:
            pack = orch.last_pack()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not load pack: {exc}", "suggestions": []}

    if pack is None:
        return {"error": "No pack found. Call get_context_pack first.", "suggestions": []}

    # Collect file paths that are already in the pack.
    pack_files: set[str] = {
        item.path_or_ref for item in pack.selected_items if item.path_or_ref
    }

    if not pack_files:
        return {"suggestions": []}

    # Try to find adjacent files via the edge repository.
    # candidate_file -> list of pack files that reference it (for ranking + reason)
    candidate_refs: dict[str, list[str]] = {}

    try:
        from storage_sqlite.database import Database
        with Database(db_path) as db:
            for pack_file in pack_files:
                # Find files that this pack file imports or is imported by (edges table)
                rows = db.connection.execute(
                    """
                    SELECT DISTINCT
                        CASE
                            WHEN source = ? THEN target
                            ELSE source
                        END AS neighbor
                    FROM edges
                    WHERE (source = ? OR target = ?)
                      AND kind IN ('imports', 'calls', 'uses')
                    """,
                    (pack_file, pack_file, pack_file),
                ).fetchall()
                for row in rows:
                    neighbor = row["neighbor"]
                    if neighbor and neighbor not in pack_files:
                        candidate_refs.setdefault(neighbor, []).append(pack_file)
    except Exception:  # noqa: BLE001
        # Edges table may not exist or schema differs — fall back to positional neighbors
        pack_file_list = sorted(pack_files)
        for i, f in enumerate(pack_file_list):
            for delta in (-1, 1):
                j = i + delta
                if 0 <= j < len(pack_file_list):
                    neighbor = pack_file_list[j]
                    if neighbor not in pack_files:
                        candidate_refs.setdefault(neighbor, []).append(f)

    if not candidate_refs:
        # Last-resort fallback: suggest filesystem siblings of pack files
        for pack_file in sorted(pack_files):
            p = root / pack_file if not Path(pack_file).is_absolute() else Path(pack_file)
            try:
                siblings = [
                    s for s in p.parent.iterdir()
                    if s.is_file() and str(s) != str(p)
                ]
                for sib in siblings[:2]:
                    rel = str(sib.relative_to(root)) if sib.is_relative_to(root) else str(sib)
                    if rel not in pack_files:
                        candidate_refs.setdefault(rel, []).append(pack_file)
            except Exception:  # noqa: BLE001
                pass

    # Rank by number of pack items that reference each candidate (descending).
    ranked = sorted(candidate_refs.items(), key=lambda kv: len(kv[1]), reverse=True)

    suggestions = []
    for file_path, refs in ranked[:limit]:
        n = len(refs)
        if n == 1:
            reason = f"Structural neighbor of {refs[0]}"
        else:
            reason = f"Referenced by {n} files in your current pack"
        suggestions.append({"file": file_path, "reason": reason})

    return {"suggestions": suggestions}


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
    from contracts.models import Observation
    from core.orchestrator import _find_project_root
    from memory.capture import capture_observation
    from memory.store import ObservationStore
    from storage_sqlite.database import Database

    root = (
        Path(project_root).resolve()
        if project_root
        else _find_project_root(Path.cwd()).resolve()
    )
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
    from contracts.models import Decision
    from core.orchestrator import _find_project_root
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


def record_feedback(
    pack_id: str,
    useful: "bool | None" = None,
    missing: "list[str] | None" = None,
    noisy: "list[str] | None" = None,
    too_much_context: bool = False,
    reason: str = "",
    files_read: "list[str] | None" = None,
    project_root: str = "",
) -> dict:
    """Record agent feedback for a context pack to improve future rankings.

    Files reported as missing get a +0.05 confidence boost in future packs.
    Files reported as noisy get a -0.10 penalty. Both adjustments apply
    only after a file accumulates ≥ 3 feedback reports.

    Args:
        pack_id: UUID of the ContextPack this feedback applies to.
        useful: True if the pack was helpful, False if not, None if not rated.
        missing: File or symbol paths that should have been included.
        noisy: File or symbol paths that were irrelevant.
        too_much_context: True if the pack contained too many items.
        reason: Free-text explanation.
        files_read: File paths the agent actually consumed from the pack
            (enables read-coverage analytics after ≥ 5 reports).
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with ``recorded`` bool and ``id`` (UUID string).
    """
    from contracts.models import PackFeedback
    from core.orchestrator import _find_project_root
    from memory.store import FeedbackStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": "Database not found. Run init first.", "recorded": False}

    fb = PackFeedback(
        pack_id=pack_id,
        useful=useful,
        missing=missing or [],
        noisy=noisy or [],
        too_much_context=too_much_context,
        reason=reason,
        files_read=files_read or [],
    )

    with Database(db_path) as db:
        fb_id = FeedbackStore(db, repo_scope=str(root)).add(fb)

    return {"recorded": True, "id": fb_id}


def list_memory(
    sort: str = "freshness",
    limit: int = 20,
    project_root: str = "",
) -> dict:
    """List stored observations ordered by freshness, confidence, or recency.

    Args:
        sort: Sort order — ``freshness`` (default), ``confidence``, or ``recent``.
        limit: Maximum number of observations to return (default 20).
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with a list of observation dicts, each including
        ``effective_confidence`` for freshness-sorted results.
    """
    from core.orchestrator import _find_project_root
    from memory.freshness import effective_confidence
    from memory.store import ObservationStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": "Database not found. Run init first.", "observations": []}

    with Database(db_path) as db:
        store = ObservationStore(db)
        if sort == "freshness":
            observations = store.list_by_freshness()[:limit]
        elif sort == "confidence":
            observations = sorted(
                store._get_all(), key=lambda o: o.confidence_score, reverse=True
            )[:limit]
        else:  # "recent" or any other value
            observations = store._get_all()[:limit]

    return {
        "observations": [
            {**o.model_dump(mode="json"), "effective_confidence": round(effective_confidence(o), 4)}
            for o in observations
        ]
    }


def mark_decision_superseded(
    old_id: str,
    new_id: str,
    project_root: str = "",
) -> dict:
    """Mark an architectural decision as superseded by another.

    Sets the old decision's status to ``superseded`` and records the UUID of
    the replacement so the link is preserved for audit purposes.

    Args:
        old_id: UUID of the decision being replaced.
        new_id: UUID of the new decision that supersedes it.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Dict with ``updated`` bool and the two UUIDs on success.
    """
    from core.orchestrator import _find_project_root
    from memory.store import DecisionStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": "Database not found. Run init first.", "updated": False}

    with Database(db_path) as db:
        DecisionStore(db).mark_superseded(old_id, new_id)

    return {"updated": True, "superseded": old_id, "superseded_by": new_id}


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
