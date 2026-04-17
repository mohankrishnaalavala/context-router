"""Orchestrator: coordinates context pack generation across plugins and rankers.

This module is the single use-case coordinator that CLI and MCP server call.
It owns the end-to-end flow:

  1. Find the project root (.context-router/ directory).
  2. Open the SQLite database.
  3. Build mode-specific ContextItem candidates from stored symbols/edges.
  4. Delegate sorting and budget enforcement to the ContextRanker.
  5. Persist the finished pack to .context-router/last-pack.json.
  6. Return the ContextPack.

Module boundary: core may import from contracts, storage-sqlite, graph-index,
and ranking.  CLI/MCP server must only import from core.
"""

from __future__ import annotations

import hashlib
import re
import threading
import warnings
from pathlib import Path
from typing import Any, Callable

from cachetools import TTLCache

from contracts.config import ContextRouterConfig, load_config
from contracts.models import ContextItem, ContextPack, RuntimeSignal
from graph_index.git_diff import GitDiffParser
from ranking import ContextRanker, estimate_tokens
from storage_sqlite.database import Database
from storage_sqlite.repositories import (
    EdgeRepository,
    PackCacheRepository,
    SymbolRepository,
)

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Fixed overhead per ContextItem in JSON transport: UUID (9), source_type (5),
# repo (5), path (10), reason (5), freshness ISO datetime (10), tags (5) ≈ 40.
_METADATA_OVERHEAD_TOKENS: int = 40


def _dedup_ranked(items: list[ContextItem]) -> tuple[list[ContextItem], int]:
    """Remove duplicate (title, path_or_ref) items from a ranked list.

    Keeps the first occurrence (highest-confidence after sort) and drops
    later duplicates. Returns the deduped list and the count dropped so
    callers can surface "N duplicates hidden" to users.

    v3 phase-1 follow-up: dedup lives here so MCP, explain last-pack, and
    --json consumers see the same deduped pack the CLI table shows.
    """
    seen: set[tuple[str, str]] = set()
    out: list[ContextItem] = []
    dropped = 0
    for item in items:
        key = (item.title.strip(), item.path_or_ref.strip().lstrip("./").lower())
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append(item)
    return out, dropped


def _estimate_item_tokens(title: str, excerpt: str) -> int:
    """Estimate token cost of a ContextItem including JSON metadata overhead."""
    return estimate_tokens(title + " " + excerpt) + _METADATA_OVERHEAD_TOKENS


def _warn_optional_subsystem_failure(
    subsystem: str,
    consequence: str,
    exc: Exception,
) -> None:
    """Emit a warning when a best-effort subsystem fails during pack generation."""
    warnings.warn(
        f"{subsystem} failed; {consequence}: {exc}",
        RuntimeWarning,
        stacklevel=2,
    )

# ---------------------------------------------------------------------------
# Configuration for candidate scoring
# ---------------------------------------------------------------------------

# Review mode: confidence per source category
_REVIEW_CONFIDENCE: dict[str, float] = {
    "changed_file": 0.95,
    "blast_radius": 0.70,
    "impacted_test": 0.60,
    "config": 0.25,
    "file": 0.20,
}

# File extensions treated as config in review mode
_CONFIG_EXTENSIONS = frozenset({"yaml", "yml", "toml", "cfg", "ini", "env"})

# Fragments in file paths that disqualify a function from being an entrypoint
_NON_ENTRYPOINT_PATH_FRAGMENTS = frozenset({
    "test_", "_test", "conftest", "fix_", "_fix", "setup", "migrate",
})

# Regex to extract filenames from query strings (e.g. "ranker.py", "main.js")
_QUERY_FILENAME_RE = re.compile(r'\b([\w][\w.-]+\.\w{2,6})\b')

# Implement mode: patterns that identify entrypoints
_ENTRYPOINT_PATTERN = re.compile(
    r"^(main|app|router|handler|endpoint|create_app|get_app|make_app|run|serve)$",
    re.IGNORECASE,
)

# Path fragments that suggest a file contains contracts / data models
_CONTRACT_PATH_FRAGMENTS = ("contract", "model", "schema", "interface", "interfaces")

# Class name patterns that suggest extension points
_EXTENSION_POINT_PATTERN = re.compile(
    r"(Base|Abstract|Protocol|Interface|Mixin)(.*)|(.+)(Base|Mixin)$",
    re.IGNORECASE,
)

# Implement mode: confidence per source category
_IMPLEMENT_CONFIDENCE: dict[str, float] = {
    "entrypoint": 0.90,
    "contract": 0.80,
    "extension_point": 0.70,
    "file_class": 0.40,
    "file_function": 0.30,
    "file": 0.20,
}

# Debug mode: confidence per source category
_DEBUG_CONFIDENCE: dict[str, float] = {
    "runtime_signal": 0.95,
    "past_debug": 0.90,       # same error seen before — files from prior fix
    "failing_test": 0.85,
    "changed_file": 0.70,
    "blast_radius": 0.50,
    "file": 0.20,
}

# Handover mode: confidence per source category
_HANDOVER_CONFIDENCE: dict[str, float] = {
    "changed_file": 0.90,
    "memory": 0.80,
    "decision": 0.75,
    "blast_radius": 0.50,
    "file": 0.15,
}


_DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "review": _REVIEW_CONFIDENCE,
    "implement": _IMPLEMENT_CONFIDENCE,
    "debug": _DEBUG_CONFIDENCE,
    "handover": _HANDOVER_CONFIDENCE,
}

# Community anchor boost (P2-1): items in the same community as the highest
# -confidence seed item get this additive bump (capped at 1.0).
_COMMUNITY_BOOST: float = 0.10


def _resolve_weights(
    mode: str, cfg: ContextRouterConfig | None
) -> dict[str, float]:
    """Return the mode's confidence dict with any user overrides merged in.

    Hardcoded defaults stay the single source of truth; overrides supply
    partial replacements. Absent config returns the defaults verbatim.
    """
    defaults = _DEFAULT_WEIGHTS.get(mode, {})
    if cfg is None or not cfg.confidence_weights:
        return defaults
    override = cfg.confidence_weights.get(mode) or {}
    if not override:
        return defaults
    merged = dict(defaults)
    merged.update({k: float(v) for k, v in override.items()})
    return merged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_project_root(start: Path) -> Path:
    """Walk up from *start* until a .context-router/ directory is found.

    Args:
        start: Directory to start searching from (typically ``Path.cwd()``).

    Returns:
        The directory that contains ``.context-router/``.

    Raises:
        FileNotFoundError: If no ``.context-router/`` directory is found
            anywhere up to the filesystem root.
    """
    current = start.resolve()
    while True:
        if (current / ".context-router").is_dir():
            return current
        parent = current.parent
        if parent == current:
            raise FileNotFoundError(
                "No .context-router/ directory found. "
                "Run 'context-router init' to initialise this project."
            )
        current = parent


def _make_item(
    sym_name: str,
    file_path: str,
    signature: str,
    docstring: str,
    source_type: str,
    confidence: float,
    repo: str,
) -> ContextItem:
    """Build a ContextItem from raw symbol fields."""
    title = f"{sym_name} ({Path(file_path).name})"
    excerpt = "\n".join(filter(None, [signature, docstring])).strip()
    return ContextItem(
        source_type=source_type,
        repo=repo,
        path_or_ref=file_path,
        title=title,
        excerpt=excerpt,
        reason="",  # will be filled in by ContextRanker.rank()
        confidence=confidence,
        est_tokens=_estimate_item_tokens(title, excerpt),
        tags=[],
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """Central coordinator for context pack generation.

    Args:
        project_root: Path to the repository root (the directory that contains
            ``.context-router/``).  When ``None``, auto-detected by walking up
            from ``Path.cwd()``.
    """

    # P3-1: Orchestrator-level cache of fully ranked ContextPack results.
    # Key: (repo_id, mode, sha256(query), budget, use_embeddings, items_hash)
    # repo_id is derived from the DB file mtime + repo_name so any
    # ``build_index`` / ``update_index`` write naturally invalidates the
    # cache. TTL protects against stale results if the index is mutated via
    # a path we don't see (e.g. another process).
    _PACK_CACHE_MAXSIZE: int = 100
    _PACK_CACHE_TTL_SECONDS: int = 300

    def __init__(self, project_root: Path | None = None) -> None:
        """Initialise the orchestrator.

        Args:
            project_root: Optional explicit project root path.
        """
        self._root = project_root or _find_project_root(Path.cwd())
        # Pack result cache (P3-1). RLock guards mutations — the MCP server
        # is single-threaded today but the CLI can spawn workers in future.
        self._pack_cache: TTLCache = TTLCache(
            maxsize=self._PACK_CACHE_MAXSIZE,
            ttl=self._PACK_CACHE_TTL_SECONDS,
        )
        self._pack_cache_lock = threading.RLock()

    # ------------------------------------------------------------------
    # Cache helpers (P3-1)
    # ------------------------------------------------------------------

    def _compute_repo_id(self, repo_name: str = "default") -> str:
        """Return a cache-busting repo identifier.

        ``sha1(symbol_shape || repo_name)`` — ``symbol_shape`` is derived
        from ``(COUNT(*), MAX(id))`` of the ``symbols`` table, which only
        moves on a real ``build_index`` / ``update_index`` run. (The DB
        file's mtime would also catch cache writes to ``pack_cache``, which
        would poison the L2 lookup — symbols-table shape is stable across
        non-index writes.)

        Falls back to ``"unindexed"`` if the DB does not yet exist or the
        ``symbols`` table is unavailable.
        """
        db_path = self._root / ".context-router" / "context-router.db"
        try:
            if not db_path.exists():
                indexed_at = "unindexed"
            else:
                import sqlite3

                with sqlite3.connect(db_path) as conn:
                    row = conn.execute(
                        "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM symbols"
                    ).fetchone()
                indexed_at = f"{row[0]}:{row[1]}" if row else "unindexed"
        except Exception:  # noqa: BLE001 — be conservative on DB errors
            indexed_at = "unindexed"
        h = hashlib.sha1()
        h.update(indexed_at.encode("utf-8"))
        h.update(b"|")
        h.update(repo_name.encode("utf-8"))
        return h.hexdigest()

    def _compute_items_hash(self, **parts: Any) -> str:
        """Hash misc inputs that affect candidate set (error_file, page params)."""
        h = hashlib.sha1()
        for key in sorted(parts.keys()):
            h.update(key.encode("utf-8"))
            h.update(b"=")
            h.update(str(parts[key]).encode("utf-8"))
            h.update(b"|")
        return h.hexdigest()

    def invalidate_cache(self) -> None:
        """Drop all cached packs (L1 in-process + L2 SQLite).

        Call after ``build_index``/``update_index``. The L2 ``pack_cache``
        table is cleared for the current ``repo_id`` (and implicitly
        invalidated for all future repo_ids by the mtime-derived key
        rotation). If the SQLite layer is unavailable we emit a stderr
        warning — per CLAUDE.md, silent failure is a bug.
        """
        with self._pack_cache_lock:
            self._pack_cache.clear()
        db_path = self._root / ".context-router" / "context-router.db"
        if not db_path.exists():
            return
        try:
            with Database(db_path) as db:
                PackCacheRepository(db.connection).invalidate_all()
        except Exception as exc:  # noqa: BLE001 — persistent cache is best-effort
            _warn_optional_subsystem_failure(
                "Persistent pack cache invalidation",
                "stale entries in .context-router/context-router.db pack_cache "
                "may survive until TTL expires",
                exc,
            )

    # ------------------------------------------------------------------
    # Persistent (L2) pack cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key_string(
        mode: str,
        query_hash: str,
        token_budget: int,
        use_embeddings: bool,
        items_hash: str,
    ) -> str:
        """Fold the cache-key tuple into a stable string for L2 storage.

        Kept separate from the L1 tuple so that the L2 primary-key column
        stays a single TEXT — the DB does not need to understand the
        structure, only compare bytes.
        """
        h = hashlib.sha1()
        for part in (
            mode,
            query_hash,
            str(token_budget),
            "1" if use_embeddings else "0",
            items_hash,
        ):
            h.update(part.encode("utf-8"))
            h.update(b"|")
        return h.hexdigest()

    def _l2_get(
        self, cache_key_str: str, repo_id: str, db_path: Path
    ) -> ContextPack | None:
        """Look up the persistent L2 cache; return None on miss or error.

        Warns to stderr (never silently skips) if the DB read fails — this
        is required by the CLAUDE.md "silent failure is a bug" rule.
        """
        try:
            with Database(db_path) as db:
                raw = PackCacheRepository(db.connection).get(
                    cache_key_str,
                    repo_id,
                    float(self._PACK_CACHE_TTL_SECONDS),
                )
        except Exception as exc:  # noqa: BLE001 — fall back to fresh build
            _warn_optional_subsystem_failure(
                "Persistent pack cache read",
                "falling back to a fresh build; the CLI repeat-call speedup "
                "will not apply for this invocation",
                exc,
            )
            return None
        if raw is None:
            return None
        try:
            return ContextPack.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 — schema drift → fresh build
            _warn_optional_subsystem_failure(
                "Persistent pack cache deserialize",
                "schema mismatch likely — rebuilding the pack and overwriting "
                "the stored row on next cache write",
                exc,
            )
            return None

    def _l2_put(
        self,
        cache_key_str: str,
        repo_id: str,
        pack: ContextPack,
        db_path: Path,
    ) -> None:
        """Write to the persistent L2 cache. Best-effort; warns on error."""
        try:
            with Database(db_path) as db:
                PackCacheRepository(db.connection).put(
                    cache_key_str, repo_id, pack.model_dump_json()
                )
        except Exception as exc:  # noqa: BLE001 — persistent cache is best-effort
            _warn_optional_subsystem_failure(
                "Persistent pack cache write",
                "CLI repeat-call speedup will not apply across processes until "
                "a subsequent build succeeds",
                exc,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_pack(
        self,
        mode: str,
        query: str,
        error_file: Path | None = None,
        page: int = 0,
        page_size: int = 0,
        use_embeddings: bool = False,
        progress: bool = True,
        progress_cb: "Callable[[str, int, int], None] | None" = None,
        download_progress_cb: Callable[[str], None] | None = None,
    ) -> ContextPack:
        """Build and return a ranked ContextPack for the given mode and query.

        Persists the result to ``.context-router/last-pack.json`` so that
        ``context-router explain last-pack`` can read it without re-running.

        Args:
            mode: One of "review", "debug", "implement", "handover".
            query: Free-text description of the task.
            error_file: Optional path to an error file (JUnit XML, stack trace,
                log).  Used by debug mode to parse RuntimeSignals.
            page: Zero-based page index for paginated responses (default 0).
                Ignored when *page_size* is 0.
            page_size: Number of items per page.  0 (default) disables pagination
                and returns all ranked items.
            use_embeddings: Opt-in semantic similarity ranking (requires
                ``sentence-transformers``; triggers a ~33 MB model download
                on first use). Defaults to False so cold-start callers pay
                no download or memory cost.
            progress: Enable the CLI's download-progress rendering. Callers
                on MCP stdio transport must pass ``progress=False`` so stdout
                progress writes never corrupt JSON-RPC frames.
            progress_cb: Pack-build progress callback used by the MCP
                dispatcher — invoked as ``progress_cb(stage, progress, total)``
                at candidate / ranked / serialized milestones plus
                per-1,000-token chunks for packs larger than 2,000 tokens.
            download_progress_cb: Status callback (single-arg string) bound
                by the CLI to a ``rich.progress.Progress`` instance for
                first-time sentence-transformers model download. Ignored
                when ``progress=False``.

        Returns:
            A populated and ranked ContextPack.

        Raises:
            FileNotFoundError: If the SQLite database does not exist (index has
                not been run yet).
            ValueError: If *mode* is not a recognised value.
        """
        config = load_config(self._root)
        repo_scope = str(self._root.resolve())
        db_path = self._root / ".context-router" / "context-router.db"

        if not db_path.exists():
            raise FileNotFoundError(
                f"Index database not found at {db_path}. "
                "Run 'context-router index' first."
            )

        # Cache lookup — identical inputs return the previously built
        # ContextPack without re-running candidate building or ranking.
        # L1 (in-process TTLCache) benefits the long-lived MCP server;
        # L2 (SQLite-backed, migration 0012) persists across CLI processes
        # so a second `context-router pack` run for the same query skips
        # the full pipeline.
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        items_hash = self._compute_items_hash(
            error_file=error_file if error_file is None else str(error_file),
            page=page,
            page_size=page_size,
        )
        repo_id = self._compute_repo_id()
        cache_key = (
            repo_id,
            mode,
            query_hash,
            int(config.token_budget),
            bool(use_embeddings),
            items_hash,
        )
        with self._pack_cache_lock:
            cached = self._pack_cache.get(cache_key)
        if cached is not None:
            return cached

        # L2 lookup — persists across CLI invocations.
        cache_key_str = self._cache_key_string(
            mode,
            query_hash,
            int(config.token_budget),
            bool(use_embeddings),
            items_hash,
        )
        l2_pack = self._l2_get(cache_key_str, repo_id, db_path)
        if l2_pack is not None:
            # Re-hydrate L1 so subsequent same-process calls are fastest.
            with self._pack_cache_lock:
                self._pack_cache[cache_key] = l2_pack
            return l2_pack

        # Model-download progress callback for the CLI's rich spinner
        # (disabled for MCP stdio transport, which has progress=False).
        effective_cb: Callable[[str], None] | None = (
            download_progress_cb if (progress and download_progress_cb is not None) else None
        )

        # Parse runtime signals from error file (debug mode)
        runtime_signals: list[RuntimeSignal] = []
        if error_file is not None:
            from runtime import parse_error_file  # local import — optional dep
            runtime_signals = parse_error_file(error_file)

        with Database(db_path) as db:
            sym_repo = SymbolRepository(db.connection)
            edge_repo = EdgeRepository(db.connection)

            # Phase 4: persist signals to DB + recall past observations by error_hash
            past_debug_files: set[str] = set()
            if runtime_signals:
                from storage_sqlite.repositories import RuntimeSignalRepository
                sig_repo = RuntimeSignalRepository(db.connection)
                for sig in runtime_signals:
                    try:
                        sig_repo.add(sig)
                    except Exception as exc:  # noqa: BLE001
                        _warn_optional_subsystem_failure(
                            "Runtime signal persistence",
                            "debug memory will omit the latest runtime signal",
                            exc,
                        )
                    # Look up past signals with the same error_hash
                    if sig.error_hash:
                        try:
                            past = sig_repo.find_by_error_hash(sig.error_hash)
                            for ps in past[1:]:  # skip the one we just inserted
                                for p in ps.paths:
                                    past_debug_files.add(str(p))
                                    past_debug_files.add(p.name)
                        except Exception as exc:  # noqa: BLE001
                            _warn_optional_subsystem_failure(
                                "Past runtime signal lookup",
                                "past_debug files will not be recalled for this build",
                                exc,
                            )

            # Phase 6: load feedback-based confidence adjustments
            try:
                from storage_sqlite.repositories import PackFeedbackRepository
                feedback_adjustments = PackFeedbackRepository(db.connection).get_file_adjustments(
                    repo_scope=repo_scope,
                )
            except Exception as exc:  # noqa: BLE001
                _warn_optional_subsystem_failure(
                    "Feedback adjustment loading",
                    "feedback-based ranking adjustments will be omitted",
                    exc,
                )
                feedback_adjustments = {}

            candidates = self._build_candidates(
                mode, sym_repo, edge_repo,
                config=config,
                runtime_signals=runtime_signals,
                past_debug_files=past_debug_files,
                feedback_adjustments=feedback_adjustments,
            )

            if progress_cb is not None:
                try:
                    progress_cb("candidates", 1, 3)
                except Exception:  # noqa: BLE001 — progress is best-effort
                    pass

            # Boost items whose file matches a filename mentioned in the query
            query_filenames = {
                m.lower() for m in _QUERY_FILENAME_RE.findall(query)
                if not m.startswith("http")
            }
            if query_filenames:
                candidates = [
                    item.model_copy(update={
                        "confidence": min(0.95, item.confidence + 0.40)
                    })
                    if any(
                        Path(item.path_or_ref).name.lower() == fn
                        for fn in query_filenames
                    )
                    else item
                    for item in candidates
                ]

            baseline = sum(c.est_tokens for c in candidates)
            # Always apply at least 50% reduction so small repos benefit too
            effective_budget = min(config.token_budget, max(1000, baseline // 2))
            ranker = ContextRanker(
                token_budget=effective_budget,
                use_embeddings=use_embeddings,
                progress_cb=effective_cb,
            )
            all_ranked = ranker.rank(candidates, query, mode)
            all_ranked, _dup_dropped = _dedup_ranked(all_ranked)
            total_items_count = len(all_ranked)

            if progress_cb is not None:
                try:
                    progress_cb("ranked", 2, 3)
                except Exception:  # noqa: BLE001 — progress is best-effort
                    pass

            # P1-8: record_access for each item in the final pack (best-effort)
            for item in all_ranked:
                try:
                    sym_repo.record_access(item.path_or_ref, item.title.split(" (")[0])
                except Exception:  # noqa: BLE001
                    pass  # best-effort

        # Apply pagination if requested
        if page_size > 0:
            start = page * page_size
            page_items = all_ranked[start : start + page_size]
            has_more = (page + 1) * page_size < total_items_count
        else:
            page_items = all_ranked
            has_more = False

        total = sum(i.est_tokens for i in page_items)
        reduction = round((baseline - sum(i.est_tokens for i in all_ranked)) / baseline * 100, 1) if baseline else 0.0

        pack = ContextPack(
            mode=mode,
            query=query,
            selected_items=page_items,
            total_est_tokens=total,
            baseline_est_tokens=baseline,
            reduction_pct=reduction,
            has_more=has_more,
            total_items=total_items_count if page_size > 0 else 0,
            duplicates_hidden=_dup_dropped,
        )

        last_pack_path = self._root / ".context-router" / "last-pack.json"
        last_pack_path.write_text(pack.model_dump_json(indent=2))

        # Populate both cache tiers so the next identical call is a hit.
        # L1 serves same-process (MCP long-lived) callers; L2 persists the
        # pack to SQLite so a CLI repeat invocation (new process) hits too.
        with self._pack_cache_lock:
            self._pack_cache[cache_key] = pack
        self._l2_put(cache_key_str, repo_id, pack, db_path)

        # Emit intermediate chunk progress for large packs so UIs can render a
        # live bar while the serialised payload is persisted downstream.
        if progress_cb is not None and total > 2_000:
            try:
                for emitted in range(0, total, 1_000):
                    progress_cb("serializing", emitted, total)
            except Exception:  # noqa: BLE001
                pass
        if progress_cb is not None:
            try:
                progress_cb("serialized", 3, 3)
            except Exception:  # noqa: BLE001
                pass

        # Persist to the pack registry so MCP `resources/list` can surface it.
        try:
            from core.pack_store import PackStore
            PackStore(self._root).save(pack)
        except Exception as exc:  # noqa: BLE001 — best-effort registry write
            _warn_optional_subsystem_failure(
                "Pack registry persistence",
                "the pack will not appear in MCP resources/list until the next successful build",
                exc,
            )

        return pack

    def list_packs(self) -> list[dict]:
        """Return registry entries for all stored packs, newest first.

        Returns:
            A list of ``{uuid, mode, query, created_at, tokens}`` dicts.
            Empty when no packs have been built yet.
        """
        from core.pack_store import PackStore
        return list(PackStore(self._root).list())

    def get_pack(self, uuid: str) -> ContextPack | None:
        """Return the stored :class:`ContextPack` with ``id == uuid``, or ``None``."""
        from core.pack_store import PackStore
        return PackStore(self._root).get(uuid)

    def get_pack_raw(self, uuid: str) -> str | None:
        """Return the stored pack's raw JSON text, byte-for-byte.

        Used by the MCP ``resources/read`` handler to keep the response
        identical to ``last-pack.json``.
        """
        from core.pack_store import PackStore
        return PackStore(self._root).read_raw(uuid)

    def last_pack(self) -> ContextPack | None:
        """Return the most recently generated ContextPack, or None.

        Reads from ``.context-router/last-pack.json``.

        Returns:
            The last ContextPack, or ``None`` if no pack has been generated yet.
        """
        path = self._root / ".context-router" / "last-pack.json"
        if not path.exists():
            return None
        return ContextPack.model_validate_json(path.read_text())

    # ------------------------------------------------------------------
    # Candidate building — dispatches by mode
    # ------------------------------------------------------------------

    def _build_candidates(
        self,
        mode: str,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str = "default",
        config: ContextRouterConfig | None = None,
        runtime_signals: list[RuntimeSignal] | None = None,
        past_debug_files: set[str] | None = None,
        feedback_adjustments: dict[str, float] | None = None,
    ) -> list[ContextItem]:
        """Fetch and pre-score candidate ContextItems for *mode*.

        Reason strings are intentionally left empty here; the ranker fills
        them in from the source_type.

        Raises:
            ValueError: If *mode* is unrecognised.
        """
        signals = runtime_signals or []
        adj = feedback_adjustments or {}
        past_files = past_debug_files or set()
        weights = _resolve_weights(mode, config)

        if mode == "review":
            items = self._review_candidates(sym_repo, edge_repo, repo_name, weights)
        elif mode == "implement":
            items = self._implement_candidates(sym_repo, repo_name, weights)
        elif mode == "debug":
            items = self._debug_candidates(
                sym_repo, edge_repo, repo_name, weights, signals, past_files
            )
        elif mode == "handover":
            items = self._handover_candidates(sym_repo, edge_repo, repo_name, weights)
        else:
            raise ValueError(f"Unknown mode: {mode!r}")

        # P2-1: community-cohesion boost — items sharing the anchor's community
        # get a small additive bump so co-changed files cluster together.
        if mode != "handover":
            items = self._apply_community_boost(items, sym_repo, repo_name)

        # Apply feedback-based confidence adjustments (Phase 6)
        if adj:
            items = [
                item.model_copy(update={
                    "confidence": max(0.0, min(0.95, item.confidence + adj[item.path_or_ref]))
                })
                if item.path_or_ref in adj
                else item
                for item in items
            ]
        return items

    @staticmethod
    def _apply_community_boost(
        items: list[ContextItem],
        sym_repo: SymbolRepository,
        repo_name: str,
    ) -> list[ContextItem]:
        """Boost candidates sharing a community with the highest-confidence item.

        Anchor is the most confident candidate whose file maps to a known
        community. When no symbol has a community assigned (e.g. graph not
        finalized yet), returns *items* unchanged so behavior is additive.
        """
        if not items:
            return items
        file_to_community: dict[str, int] = {}
        try:
            for sym in sym_repo.get_all(repo_name):
                if sym.community_id is None:
                    continue
                key = str(sym.file)
                if key not in file_to_community:
                    file_to_community[key] = sym.community_id
        except Exception:  # noqa: BLE001
            return items
        if not file_to_community:
            return items
        anchor_community: int | None = None
        for item in sorted(items, key=lambda i: i.confidence, reverse=True):
            cid = file_to_community.get(item.path_or_ref)
            if cid is not None:
                anchor_community = cid
                break
        if anchor_community is None:
            return items
        boosted: list[ContextItem] = []
        for item in items:
            cid = file_to_community.get(item.path_or_ref)
            if cid == anchor_community:
                boosted.append(item.model_copy(update={
                    "confidence": min(1.0, item.confidence + _COMMUNITY_BOOST)
                }))
            else:
                boosted.append(item)
        return boosted

    # ------------------------------------------------------------------
    # Review mode
    # ------------------------------------------------------------------

    def _review_candidates(
        self,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str,
        weights: dict[str, float],
    ) -> list[ContextItem]:
        """Build candidates prioritised for a code-review task."""
        changed_files = self._get_changed_files()
        all_symbols = sym_repo.get_all(repo_name)

        # Pre-compute adjacency for changed files (blast radius, depth=1)
        blast_radius_files: set[str] = set()
        for cf in changed_files:
            adjacent = edge_repo.get_adjacent_files(repo_name, cf)
            blast_radius_files.update(adjacent)
        blast_radius_files -= changed_files  # don't double-count

        # P1-5: compute transitive blast radius (depth=2) via call chain
        transitive_blast_files: dict[str, int] = {}  # file_path -> min_depth
        for cf in changed_files:
            chain = edge_repo.get_call_chain_files(repo_name, cf, max_depth=2)
            for fp, depth in chain:
                if fp not in changed_files and fp not in blast_radius_files:
                    if fp not in transitive_blast_files or depth < transitive_blast_files[fp]:
                        transitive_blast_files[fp] = depth

        seen_files: set[str] = set()
        items: list[ContextItem] = []

        for sym in all_symbols:
            fp = str(sym.file)

            if fp in changed_files:
                source_type = "changed_file"
            elif fp in blast_radius_files:
                source_type = "blast_radius"
            elif self._is_test_file(fp) and self._matches_changed(fp, changed_files):
                source_type = "impacted_test"
            elif sym.file.suffix.lstrip(".") in _CONFIG_EXTENSIONS:
                source_type = "config"
            else:
                source_type = "file"

            confidence = weights.get(source_type, _REVIEW_CONFIDENCE[source_type])
            seen_files.add(fp)
            items.append(
                _make_item(
                    sym_name=sym.name,
                    file_path=fp,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    source_type=source_type,
                    confidence=confidence,
                    repo=repo_name,
                )
            )

        # P1-5: add transitive blast radius items not already in the pack
        existing_paths = {item.path_or_ref for item in items}
        for fp, _depth in transitive_blast_files.items():
            if fp not in existing_paths:
                title = f"{Path(fp).name} (blast radius transitive)"
                items.append(
                    ContextItem(
                        source_type="blast_radius_transitive",
                        repo=repo_name,
                        path_or_ref=fp,
                        title=title,
                        excerpt="",
                        reason="",
                        confidence=0.35,
                        est_tokens=_estimate_item_tokens(title, ""),
                    )
                )

        return items

    def _get_changed_files(self) -> set[str]:
        """Return the set of file paths changed since HEAD~1.

        Falls back to an empty set if the git command fails (e.g. on a repo
        with only one commit, or when run outside a git repo).

        Returns:
            Set of absolute-or-repo-relative path strings.
        """
        try:
            changed = GitDiffParser.from_git(self._root, "HEAD~1")
            return {str(self._root / cf.path) for cf in changed}
        except (RuntimeError, OSError):
            return set()

    @staticmethod
    def _is_test_file(file_path: str) -> bool:
        """Return True if *file_path* looks like a test file."""
        name = Path(file_path).stem
        return name.startswith("test_") or name.endswith("_test")

    @staticmethod
    def _matches_changed(test_path: str, changed_files: set[str]) -> bool:
        """Return True if *test_path* plausibly tests one of *changed_files*.

        Checks whether the test file's stem (with leading "test_" removed)
        matches the stem of any changed source file.
        """
        test_stem = Path(test_path).stem
        # Strip test_ prefix or _test suffix to get the module name
        if test_stem.startswith("test_"):
            module = test_stem[5:]
        elif test_stem.endswith("_test"):
            module = test_stem[:-5]
        else:
            module = test_stem

        return any(Path(cf).stem == module for cf in changed_files)

    # ------------------------------------------------------------------
    # Implement mode
    # ------------------------------------------------------------------

    def _implement_candidates(
        self,
        sym_repo: SymbolRepository,
        repo_name: str,
        weights: dict[str, float],
    ) -> list[ContextItem]:
        """Build candidates prioritised for a feature-implementation task."""
        all_symbols = sym_repo.get_all(repo_name)
        items: list[ContextItem] = []

        for sym in all_symbols:
            fp = str(sym.file)
            source_type, confidence = self._classify_for_implement(
                sym.name, sym.kind, fp, weights
            )
            items.append(
                _make_item(
                    sym_name=sym.name,
                    file_path=fp,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    source_type=source_type,
                    confidence=confidence,
                    repo=repo_name,
                )
            )

        return items

    @staticmethod
    def _classify_for_implement(
        name: str, kind: str, file_path: str, weights: dict[str, float] | None = None
    ) -> tuple[str, float]:
        """Classify a symbol for implement-mode scoring."""
        effective = weights if weights is not None else _IMPLEMENT_CONFIDENCE

        def w(key: str) -> float:
            return effective.get(key, _IMPLEMENT_CONFIDENCE[key])

        # Entrypoints: well-known function/method names
        if kind in ("function", "method") and _ENTRYPOINT_PATTERN.match(name):
            file_name = Path(file_path).name.lower()
            is_non_entrypoint = any(
                frag in file_name for frag in _NON_ENTRYPOINT_PATH_FRAGMENTS
            )
            if not is_non_entrypoint:
                return "entrypoint", w("entrypoint")

        # Contracts: files whose path contains model/schema/contract keywords
        fp_lower = file_path.lower()
        if any(fragment in fp_lower for fragment in _CONTRACT_PATH_FRAGMENTS):
            return "contract", w("contract")

        # Extension points: abstract base classes / protocol classes
        if kind == "class" and _EXTENSION_POINT_PATTERN.search(name):
            return "extension_point", w("extension_point")

        if kind == "class":
            return "file", w("file_class")

        if kind in ("function", "method"):
            return "file", w("file_function")

        return "file", w("file")

    # ------------------------------------------------------------------
    # Debug mode
    # ------------------------------------------------------------------

    def _debug_candidates(
        self,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str,
        weights: dict[str, float],
        signals: list[RuntimeSignal],
        past_debug_files: set[str] | None = None,
    ) -> list[ContextItem]:
        """Build candidates prioritised for a debug task.

        Priority:
          runtime_signal (0.95) > past_debug (0.90) > failing_test (0.85)
          > changed_file (0.70) > blast_radius (0.50) > file (0.20)
        """
        past_files = past_debug_files or set()

        # Collect file paths mentioned in runtime signals
        signal_paths: set[str] = set()
        for sig in signals:
            for p in sig.paths:
                signal_paths.add(str(p))
                # Also try matching by filename alone (relative vs absolute)
                signal_paths.add(p.name)

        changed_files = self._get_changed_files()

        blast_radius_files: set[str] = set()
        for cf in changed_files:
            blast_radius_files.update(edge_repo.get_adjacent_files(repo_name, cf))
        blast_radius_files -= changed_files

        all_symbols = sym_repo.get_all(repo_name)
        items: list[ContextItem] = []

        # Add RuntimeSignal items first (one item per signal, not per symbol)
        seen_signal_messages: set[str] = set()
        for sig in signals:
            if sig.message in seen_signal_messages:
                continue
            seen_signal_messages.add(sig.message)
            excerpt = "\n".join(sig.stack[:10]) if sig.stack else sig.message
            title = sig.message[:80]
            items.append(
                ContextItem(
                    source_type="runtime_signal",
                    repo=repo_name,
                    path_or_ref=str(sig.paths[0]) if sig.paths else "runtime",
                    title=title,
                    excerpt=excerpt,
                    reason="",
                    confidence=weights.get("runtime_signal", _DEBUG_CONFIDENCE["runtime_signal"]),
                    est_tokens=_estimate_item_tokens(title, excerpt),
                )
            )

        for sym in all_symbols:
            fp = str(sym.file)
            fname = sym.file.name

            if fp in signal_paths or fname in signal_paths:
                source_type = "runtime_signal"
                confidence = weights.get("runtime_signal", _DEBUG_CONFIDENCE["runtime_signal"])
            elif fp in past_files or fname in past_files:
                source_type = "past_debug"
                confidence = weights.get("past_debug", _DEBUG_CONFIDENCE.get("past_debug", 0.90))
            elif self._is_test_file(fp):
                source_type = "failing_test"
                confidence = weights.get("failing_test", _DEBUG_CONFIDENCE["failing_test"])
            elif fp in changed_files:
                source_type = "changed_file"
                confidence = weights.get("changed_file", _DEBUG_CONFIDENCE["changed_file"])
            elif fp in blast_radius_files:
                source_type = "blast_radius"
                confidence = weights.get("blast_radius", _DEBUG_CONFIDENCE["blast_radius"])
            else:
                source_type = "file"
                confidence = weights.get("file", _DEBUG_CONFIDENCE["file"])

            items.append(
                _make_item(
                    sym_name=sym.name,
                    file_path=fp,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    source_type=source_type,
                    confidence=confidence,
                    repo=repo_name,
                )
            )

        # P5: Walk 'calls' edges from runtime_signal/changed_file paths to
        # surface call chains leading to the error site (up to 3 hops).
        # Confidence decays by _CALL_CHAIN_DECAY per hop.
        _CALL_CHAIN_BASE_CONF = 0.45
        _CALL_CHAIN_DECAY = 0.70  # multiplier per hop

        existing_paths = {item.path_or_ref for item in items}
        call_chain_items: list[ContextItem] = []
        seen_chain_paths: set[str] = set(existing_paths)

        for item in items:
            if item.source_type not in ("runtime_signal", "changed_file"):
                continue
            chain_files = edge_repo.get_call_chain_files(
                repo_name, item.path_or_ref, max_depth=3
            )
            for chain_file, depth in chain_files:
                if chain_file in seen_chain_paths:
                    continue
                seen_chain_paths.add(chain_file)
                conf = round(_CALL_CHAIN_BASE_CONF * (_CALL_CHAIN_DECAY ** (depth - 1)), 4)
                title = f"{Path(chain_file).name} (call chain depth {depth})"
                call_chain_items.append(
                    ContextItem(
                        source_type="call_chain",
                        repo=repo_name,
                        path_or_ref=chain_file,
                        title=title,
                        excerpt="",
                        reason="",
                        confidence=conf,
                        est_tokens=_estimate_item_tokens(title, ""),
                    )
                )
        items.extend(call_chain_items)

        return items

    # ------------------------------------------------------------------
    # Handover mode
    # ------------------------------------------------------------------

    def _handover_candidates(
        self,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str,
        weights: dict[str, float],
    ) -> list[ContextItem]:
        """Build candidates for a project handover pack.

        Combines changed files, stored observations (memory), and decisions.
        """
        changed_files = self._get_changed_files()

        blast_radius_files: set[str] = set()
        for cf in changed_files:
            blast_radius_files.update(edge_repo.get_adjacent_files(repo_name, cf))
        blast_radius_files -= changed_files

        all_symbols = sym_repo.get_all(repo_name)
        items: list[ContextItem] = []

        # Symbol-based items (changed + blast radius)
        for sym in all_symbols:
            fp = str(sym.file)
            if fp in changed_files:
                source_type = "changed_file"
                confidence = weights.get("changed_file", _HANDOVER_CONFIDENCE["changed_file"])
            elif fp in blast_radius_files:
                source_type = "blast_radius"
                confidence = weights.get("blast_radius", _HANDOVER_CONFIDENCE["blast_radius"])
            else:
                source_type = "file"
                confidence = weights.get("file", _HANDOVER_CONFIDENCE["file"])

            items.append(
                _make_item(
                    sym_name=sym.name,
                    file_path=fp,
                    signature=sym.signature,
                    docstring=sym.docstring,
                    source_type=source_type,
                    confidence=confidence,
                    repo=repo_name,
                )
            )

        # Memory items: observations and decisions from the store
        db_path = self._root / ".context-router" / "context-router.db"
        try:
            from memory.store import DecisionStore, ObservationStore
            with Database(db_path) as db:
                obs_store = ObservationStore(db)
                dec_store = DecisionStore(db)

                from memory.freshness import score_for_pack
                for obs in obs_store.list_by_freshness():
                    excerpt = obs.summary
                    if obs.fix_summary:
                        excerpt = f"{obs.summary}\nFix: {obs.fix_summary}"
                    # Use freshness-weighted score, capped at the handover base
                    fresh_conf = min(
                        weights.get("memory", _HANDOVER_CONFIDENCE["memory"]),
                        max(0.10, score_for_pack(obs)),
                    )
                    mem_title = f"Observation: {obs.summary[:60]}"
                    items.append(
                        ContextItem(
                            source_type="memory",
                            repo=repo_name,
                            path_or_ref=obs.commit_sha or "memory",
                            title=mem_title,
                            excerpt=excerpt,
                            reason="",
                            confidence=fresh_conf,
                            est_tokens=_estimate_item_tokens(mem_title, excerpt),
                        )
                    )

                for dec in dec_store.get_all():
                    if dec.status == "superseded":
                        continue  # skip superseded decisions
                    excerpt = dec.title
                    if dec.decision:
                        excerpt = f"{dec.title}\n{dec.decision}"
                    # Fresh decisions get full confidence; older ones decay slightly
                    from contracts.models import Observation as _Obs
                    from memory.freshness import compute_freshness as _cf
                    _dummy = _Obs(summary="", timestamp=dec.created_at)
                    _dummy = _dummy.model_copy(update={"confidence_score": dec.confidence})
                    dec_fresh = min(
                        weights.get("decision", _HANDOVER_CONFIDENCE["decision"]),
                        max(0.10, _cf(_dummy) * dec.confidence),
                    )
                    dec_title = f"Decision: {dec.title[:60]}"
                    items.append(
                        ContextItem(
                            source_type="decision",
                            repo=repo_name,
                            path_or_ref=dec.id,
                            title=dec_title,
                            excerpt=excerpt,
                            reason="",
                            confidence=dec_fresh,
                            est_tokens=_estimate_item_tokens(dec_title, excerpt),
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            _warn_optional_subsystem_failure(
                "Handover memory loading",
                "memory and decision items will be omitted from the handover pack",
                exc,
            )

        return items
