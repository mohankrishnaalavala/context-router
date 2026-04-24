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


_REVIEW_DIFFLESS_MSG = (
    "review mode expects a diff; for query-only input, try --mode debug"
)


def _maybe_warn_review_needs_diff(project_root: str) -> None:
    """Mirror of the CLI mode-mismatch warning for MCP callers.

    Sends an MCP ``notifications/message`` (level=warning) when
    ``get_context_pack(mode="review", query="...")`` runs against a clean
    git tree, and a ``level=info`` skip notice on non-git / git-error
    trees so the absence of the warning is never silent.

    Writes go through ``main._notify`` so they share the stdout
    ``_write_lock`` and cannot interleave with JSON-RPC responses.
    Falls back to stderr if the server module isn't importable (e.g.
    tools.py is exercised directly by a unit test).
    """
    import subprocess
    import sys

    root = Path(project_root).resolve() if project_root else Path.cwd()

    try:
        unstaged = subprocess.run(
            ["git", "diff", "--quiet"],
            cwd=str(root),
            capture_output=True,
            check=False,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(root),
            capture_output=True,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        _emit_mcp_log(
            "info",
            f"review-mode diff check skipped ({type(exc).__name__}: {exc})",
        )
        return

    if unstaged.returncode >= 2 or staged.returncode >= 2:
        reason = (unstaged.stderr or staged.stderr or b"").decode(
            "utf-8", errors="replace"
        ).strip()
        _emit_mcp_log(
            "info",
            f"review-mode diff check skipped (not a git repo or git error: {reason})",
        )
        return

    if unstaged.returncode == 0 and staged.returncode == 0:
        _emit_mcp_log("warning", _REVIEW_DIFFLESS_MSG)
        # Also mirror to stderr — keeps non-MCP callers (unit tests,
        # programmatic invocations) observable without JSON-RPC framing.
        print(f"warning: {_REVIEW_DIFFLESS_MSG}", file=sys.stderr)


def _emit_mcp_log(level: str, text: str) -> None:
    """Send a ``notifications/message`` frame to the MCP client.

    Falls back to stderr if the server module isn't loaded (unit tests
    call the tool function directly, outside the stdio transport).
    """
    try:
        from mcp_server.main import _notify  # local import — transport layer
    except Exception:  # noqa: BLE001 — fallback keeps the warning audible
        import sys
        print(f"[mcp-server] {level}: {text}", file=sys.stderr)
        return
    try:
        _notify(
            "notifications/message",
            {"level": level, "logger": "context-router", "data": text},
        )
    except Exception as exc:  # noqa: BLE001 — never crash the tool response
        import sys
        print(
            f"[mcp-server] notifications/message failed ({exc}); text: {text}",
            file=sys.stderr,
        )


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
    use_embeddings: bool = False,
    top_k: int = 0,
    progress_cb=None,
    pre_fix: str = "",
    keep_low_signal: bool = False,
    use_workspace: bool = False,
    use_memory: bool = False,
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
        use_embeddings: Opt-in semantic ranking (triggers a one-time ~33 MB
            model download). Defaults to False.
        top_k: Cap ``selected_items`` at N after ranking. 0 (default) applies
            no cap; negative values are treated as 0 with a stderr warning.
            When the ranked pool has fewer than ``top_k`` items, the full
            pool is returned unchanged (no warning).
        progress_cb: Optional ``(stage, progress, total)`` callable invoked at
            build milestones.  Supplied by the MCP dispatcher when the caller
            sends a ``progressToken``; normal CLI callers leave this ``None``.
        pre_fix: Optional commit SHA. Only meaningful with ``mode="review"``.
            Treats the diff of ``<sha>^..<sha>`` as the change-set so the
            pack is ranked as if the working tree were at ``<sha>^``.
            Returns ``{"error": ...}`` (no traceback) when the SHA is not
            found or the combination is invalid.
        keep_low_signal: Review-mode escape hatch (v3.2 ``review-tail-cutoff``).
            When ``False`` (default), review-mode packs drop trailing
            ``source_type="file"`` items with confidence < 0.3 once the
            token budget has been filled by structurally-important items
            (``changed_file``, ``blast_radius``, ``config``). Pass
            ``True`` to preserve the full tail — only useful for
            debugging ranker output. Ignored with a stderr warning for
            non-review modes.
        use_memory: When ``True``, append a ``memory_hits`` list of the top-8
            BM25+recency ranked observation excerpts to the returned dict.
            If the memory directory does not exist or contains no observations,
            ``memory_hits`` is set to ``[]`` silently (no stderr output).

    Returns:
        Serialised ContextPack as a dict, or {"text": ...} when format="compact".
        When ``use_memory=True``, the dict also contains a ``memory_hits`` key.
    """
    # Reject pre_fix with a non-review mode loudly — otherwise the flag
    # would silently no-op, and silent failures are banned (CLAUDE.md).
    if pre_fix and mode != "review":
        return {"error": "pre_fix is only valid with mode='review'"}

    # Silent-failure rule (mode-mismatch-warning): warn callers who invoke
    # review mode with only a free-text query against a clean tree. We
    # emit an MCP ``notifications/message`` (level=warning) — writing to
    # stdout would corrupt JSON-RPC framing, and silent no-op is banned.
    # Skipped when pre_fix is set because the diff source is the commit,
    # not the working tree — the warning would be misleading noise.
    if mode == "review" and query.strip() and not pre_fix:
        _maybe_warn_review_needs_diff(project_root)

    # Silent-failure rule: negative top_k is a silent no-op under a naive
    # truncate. Normalise to "no cap" and warn on stderr — stdout is
    # reserved for JSON-RPC frames on the MCP transport.
    if top_k is not None and top_k < 0:
        import sys
        print(
            f"warning: top_k={top_k} is negative; ignoring (no cap applied).",
            file=sys.stderr,
            flush=True,
        )
        top_k = 0

    # Silent-failure rule: keep_low_signal is a review-mode-only escape
    # hatch. Passing it in another mode is a no-op, so warn on stderr
    # (stdout is reserved for JSON-RPC frames).
    if keep_low_signal and mode != "review":
        import sys
        print(
            "warning: keep_low_signal has no effect outside mode='review' "
            f"(current mode={mode!r}); ignoring.",
            file=sys.stderr,
            flush=True,
        )

    # Resolve the orchestrator: WorkspaceOrchestrator when use_workspace=True
    # and workspace.yaml exists; regular Orchestrator otherwise.
    # Silent-failure rule: use_workspace=True with no workspace.yaml must
    # warn on stderr (stdout is reserved for JSON-RPC frames) so the
    # caller knows the flag had no effect.
    if use_workspace:
        import sys as _sys
        _ws_root = Path(project_root).resolve() if project_root else Path.cwd()
        if (_ws_root / "workspace.yaml").exists():
            from core.workspace_orchestrator import WorkspaceOrchestrator
            _orch = WorkspaceOrchestrator(workspace_root=_ws_root)
        else:
            print(
                f"warning: use_workspace=True but no workspace.yaml found at {_ws_root}; "
                "falling back to single-repo orchestrator.",
                file=_sys.stderr,
                flush=True,
            )
            _orch = _orchestrator(project_root)
    else:
        _orch = _orchestrator(project_root)

    # Only forward pre_fix as a kwarg when the caller actually supplied one
    # — keeps the existing ``build_pack`` call shape identical for the vast
    # majority of callers (including test mocks that don't accept the new
    # parameter) and only widens the signature for the review/pre-fix path.
    build_pack_kwargs: dict = {
        "page": page,
        "page_size": page_size,
        "use_embeddings": use_embeddings,
        "progress": False,
        "progress_cb": progress_cb,
    }
    if pre_fix:
        build_pack_kwargs["pre_fix"] = pre_fix
    # Only forward keep_low_signal when the caller opted in, so pre-existing
    # test mocks that don't declare the kwarg continue to work untouched.
    if keep_low_signal:
        build_pack_kwargs["keep_low_signal"] = True
    try:
        # progress=False is critical on MCP stdio transport — stdout is
        # reserved for JSON-RPC frames; any progress output would corrupt it.
        pack = _orch.build_pack(
            mode,
            query,
            **build_pack_kwargs,
        )
        # Apply the caller-facing cap post-ranking. No cap when ``top_k``
        # is 0/unset; when the pool is smaller than the cap, the full pool
        # is returned unchanged (documented; no warning).
        if top_k and top_k > 0 and len(pack.selected_items) > top_k:
            pack.selected_items = pack.selected_items[:top_k]
            try:
                pack.total_est_tokens = sum(
                    int(getattr(i, "est_tokens", 0) or 0) for i in pack.selected_items
                )
            except Exception:  # noqa: BLE001
                pass
            if hasattr(pack, "total_items"):
                try:
                    pack.total_items = len(pack.selected_items)
                except Exception:  # noqa: BLE001
                    pass
        if format == "compact":
            result = {"text": pack.to_compact_text(), "has_more": pack.has_more, "total_items": pack.total_items}
        else:
            result = pack.model_dump(mode="json")

        # use_memory: inject BM25+recency ranked observation excerpts.
        # MCP tools must not print to stderr unexpectedly, so no-observations
        # is a silent empty list (not a warning).
        if use_memory:
            from memory.file_retriever import retrieve_observations

            _root = Path(project_root).resolve() if project_root else Path.cwd()
            _memory_dir = _root / ".context-router" / "memory"
            try:
                _hits = retrieve_observations(query, _memory_dir, k=8, project_root=_root)
            except Exception:  # noqa: BLE001 — memory retrieval is best-effort
                _hits = []
            result["memory_hits"] = [
                {
                    "id": h.id,
                    "excerpt": h.excerpt,
                    "score": round(h.score, 4),
                    "files_touched": h.files_touched,
                    "task": h.task,
                    "provenance": h.provenance,
                }
                for h in _hits
            ]
            result["memory_hits_summary"] = {
                "committed": sum(1 for h in _hits if h.provenance == "committed"),
                "staged": sum(1 for h in _hits if h.provenance == "staged"),
            }

        _total_tokens = sum(i.est_tokens for i in pack.selected_items)
        _mem_tokens = sum(
            i.est_tokens for i in pack.selected_items
            if i.source_type in {"memory", "decision"}
        )
        result["budget"] = {
            "total_tokens": _total_tokens,
            "memory_tokens": _mem_tokens,
            "memory_ratio": round(_mem_tokens / _total_tokens, 4) if _total_tokens > 0 else 0.0,
        }

        return result
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


def get_minimal_context(
    task: str,
    max_tokens: int = 800,
    project_root: str = "",
) -> dict:
    """Return a token-cheap triage pack (≤5 items) plus a next-tool hint.

    Mirrors the `get_minimal_context` contract shipped by code-review-graph:
    a small, fixed-budget preview intended to let callers decide whether to
    escalate to a fuller pack or a debug pack. The returned ContextPack uses
    ``mode="minimal"`` and surfaces a ``metadata.next_tool_suggestion`` hint
    derived from the top-ranked items.

    Args:
        task: Free-text description of the task. Required; empty string is
            rejected with JSON-RPC error code -32602 (invalid params).
        max_tokens: Hard cap on the ranker's token budget. Default 800.
        project_root: Project root. Auto-detected if omitted.

    Returns:
        Serialised ContextPack dict, or an ``{"error", "code": -32602}``
        dict when ``task`` is empty/whitespace.
    """
    if not task or not task.strip():
        return {
            "error": "task cannot be empty",
            "code": -32602,
        }
    try:
        pack = _orchestrator(project_root).build_pack(
            mode="minimal",
            query=task,
            progress=False,
            token_budget=int(max_tokens) if max_tokens else 800,
        )
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    except ValueError as exc:
        return {"error": str(exc)}
    return pack.model_dump(mode="json")


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

    from memory.file_writer import MemoryFileWriter
    memory_dir = root / ".context-router" / "memory"
    writer = MemoryFileWriter(memory_dir)
    file_result = writer.write_observation(obs)
    writer.update_index()

    result: dict = {"saved": True, "id": row_id}
    if file_result.written:
        result["file"] = str(file_result.path)
    return result


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


def get_call_chain(
    symbol_id: int,
    max_depth: int = 3,
    project_root: str = "",
    repo_name: str = "default",
) -> dict:
    """Walk the ``calls`` edges from ``symbol_id`` and return downstream symbols.

    This surfaces ``EdgeRepository.get_call_chain_symbols`` — the storage-layer
    BFS that returns actual symbol objects (with file, language, line numbers)
    rather than bare file paths, which is what an AI agent needs when tracing
    execution flow.

    Args:
        symbol_id: Seed symbol id to walk from.
        max_depth: Maximum number of call-chain hops. ``0`` returns an empty
            list (silent no-op — symbol IDs may legitimately not exist and
            max_depth=0 is treated as an explicit request for "no hops").
        project_root: Path to project root. Auto-detected if omitted.
        repo_name: Logical repository name.

    Returns:
        Dict with key ``items`` → list of symbol dicts, each with keys
        ``id``, ``name``, ``kind``, ``file``, ``language``, ``line_start``,
        ``line_end``, ``depth``.  Returns ``{"items": []}`` for
        ``max_depth=0`` or an unknown ``symbol_id`` — not an error.
    """
    import sys as _sys
    from dataclasses import asdict

    from core.orchestrator import _find_project_root
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import EdgeRepository

    # Negative case: max_depth=0 returns an empty list, not an error.
    if max_depth <= 0:
        return {"items": []}

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        return {"error": f"Database not found at {db_path}. Run init first.", "items": []}

    with Database(db_path) as db:
        repo = EdgeRepository(db.connection)
        refs = repo.get_call_chain_symbols(
            repo=repo_name,
            from_symbol_id=symbol_id,
            max_depth=max_depth,
        )

    items: list[dict] = []
    for ref in refs:
        d = asdict(ref)
        # dataclasses.asdict keeps Path as-is; JSON-RPC must serialise it.
        d["file"] = str(ref.file)
        items.append(d)

    if not items:
        # CLAUDE.md silent-failure rule: emit a stderr debug note so callers
        # (and tests) can distinguish "seed absent / no callees" from an error.
        print(
            f"[get_call_chain] no callees for symbol_id={symbol_id} "
            f"in repo={repo_name!r} (seed may not exist or has no outgoing calls edges)",
            file=_sys.stderr,
        )

    return {"items": items}


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
