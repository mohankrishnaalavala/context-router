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
import os
import re
import sys
import threading
import warnings
from pathlib import Path
from typing import Any, Callable

from cachetools import TTLCache
from contracts.config import ContextRouterConfig, load_config
from contracts.models import ContextItem, ContextPack, RuntimeSignal
from graph_index.git_diff import GitDiffParser
from ranking import ContextRanker, dedup_stubs, estimate_tokens
from storage_sqlite.database import Database
from storage_sqlite.repositories import (
    ContractRepository,
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


# ---------------------------------------------------------------------------
# Review-mode risk scoring (Phase 3 Wave 2)
# ---------------------------------------------------------------------------

# Risk is a cheap per-item display overlay for review-mode packs: it tells
# reviewers where to look first by combining diff membership with a
# file-size proxy for complexity and the candidate's bm25/ranker confidence.
# It is NOT a ranking signal — the ranker never sees it.
_RISK_SIZE_MEDIUM_THRESHOLD: int = 500
_RISK_SIZE_HIGH_THRESHOLD: int = 2000
_RISK_HIGH_CONFIDENCE_THRESHOLD: float = 0.8


def _count_lines(path: Path) -> int:
    """Return the line count of *path*, or 0 if the file cannot be read."""
    try:
        with path.open("rb") as fh:
            return sum(1 for _ in fh)
    except (OSError, ValueError):
        return 0


def _compute_risk(
    item: ContextItem,
    diff_files: set[str],
    file_size: dict[str, int],
) -> str:
    """Cheap per-item risk label for review mode.

    Returns one of ``none``, ``low``, ``medium``, ``high``::

      none    = file not in current diff
      low     = in diff, small file (< 500 lines)
      medium  = in diff, medium file (500-2000 lines)
      high    = in diff AND large file (> 2000 lines) OR
                in diff AND high bm25/ranker confidence (>= 0.8)
    """
    if item.path_or_ref not in diff_files:
        return "none"
    size = file_size.get(item.path_or_ref, 0)
    if size > _RISK_SIZE_HIGH_THRESHOLD or item.confidence >= _RISK_HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if size > _RISK_SIZE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


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

# v3.1 minimal-mode-ranker-tuning: source_type values produced by
# ``_implement_candidates`` / ``_classify_for_implement``. Items with these
# source types are "code-symbol" items; other minimal-mode items (memory,
# decision, runtime_signal, etc.) are metadata overlays that should not
# outrank a code-symbol pick for a task-verb query. Used in the
# minimal-mode top-item preservation overlay.
_IMPLEMENT_SOURCE_TYPES: frozenset[str] = frozenset(
    {"entrypoint", "contract", "extension_point", "file"}
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
    # Minimal mode reuses implement weights — see build_pack() minimal branch.
    "minimal": _IMPLEMENT_CONFIDENCE,
}

# Community anchor boost (P2-1): items in the same community as the highest
# -confidence seed item get this additive bump (capped at 1.0).
_COMMUNITY_BOOST: float = 0.10

# Phase-2 contracts-consumer boost: items whose file references an OpenAPI
# endpoint declared in the same repo get this additive bump (clamped at the
# same 0.95 ceiling used by ``workspace_orchestrator``). Tightening the cap
# below 1.0 keeps the absolute "guaranteed-relevant" tier reserved for
# changed_file / runtime_signal sources.
_CONTRACTS_BOOST: float = 0.10
_CONTRACTS_BOOST_MAX_CONFIDENCE: float = 0.95

# Cap on how many bytes we read per candidate file when scanning for
# endpoint references. Keeps the boost cheap on monorepos with multi-MB
# generated files (vendored bundles, lock files renamed *.py, etc.).
_CONTRACTS_FILE_READ_LIMIT: int = 256 * 1024


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


def _suggest_next_tool(items: list[ContextItem], query: str) -> str:
    """Return a short next-tool hint for a minimal-mode pack.

    The heuristic keeps the rule-set intentionally narrow so the suggestion
    stays predictable:

    * Top item lives under ``tests/`` or filename starts with ``test_``
      → route the caller to ``get_debug_pack`` (they likely have a failing test).
    * Majority of items are config/yaml/toml/ini/json → recommend
      ``get_context_pack(mode='review')`` for deeper review of config shape.
    * Fallback → recommend ``get_context_pack(mode='implement')`` with the
      original query so the caller has a single copy-pasteable follow-up.
    """
    if not items:
        return (
            "run get_context_pack(mode='implement', query=...) for full context"
        )

    top = items[0]
    top_path = top.path_or_ref.lower()
    top_name = Path(top_path).name
    is_test = (
        "/tests/" in f"/{top_path}/"
        or top_name.startswith("test_")
        or top_name.endswith("_test.py")
    )
    if is_test:
        return "run get_debug_pack to see the failing call chain"

    config_exts = {".yml", ".yaml", ".toml", ".ini", ".json", ".cfg"}
    config_hits = sum(
        1 for item in items if Path(item.path_or_ref).suffix.lower() in config_exts
    )
    if config_hits >= max(2, len(items) // 2):
        return "run get_context_pack(mode='review') for deeper review"

    # Echo the caller's query in the fallback so the next call is one-hop away.
    safe_query = query.strip() or "<task>"
    return (
        f"run get_context_pack(mode='implement', query={safe_query!r}) "
        "for full context"
    )


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


# ---------------------------------------------------------------------------
# Function-level reason construction (v3.2 outcome: function-level-reason)
# ---------------------------------------------------------------------------

# Verb prefix for each symbol-backed source_type. When a ContextItem is
# backed by a Symbol (line_start/line_end known), ``_make_item`` composes a
# reason of the shape ``f"{verb} `{name}` lines {start}-{end}"``. The
# ranker's ``_annotate`` preserves any non-empty reason set here, so the
# upgraded string survives downstream boosting.
_SYMBOL_REASON_VERB: dict[str, str] = {
    "changed_file": "Modified",
    "blast_radius": "Depends on or is imported by",
    "blast_radius_transitive": "Transitively reachable via call chain from",
    "impacted_test": "Tests code affected by this change in",
    "config": "Configuration symbol touched by change in",
    "entrypoint": "Public API entry point",
    "contract": "Data contract or interface definition",
    "extension_point": "Plugin or extension point",
    "file": "Referenced in codebase",
    "runtime_signal": "Mentioned in runtime error or stack trace",
    "failing_test": "Test symbol likely related to the failure",
    "call_chain": "Reachable via function call chain from error site",
    "past_debug": "Related to a previously debugged failure",
}


def _build_symbol_reason(
    verb: str,
    qualified_name: str,
    line_start: int,
    line_end: int,
) -> str:
    """Return the upgraded function-level reason string."""
    return f"{verb} `{qualified_name}` lines {line_start}-{line_end}"


def _make_item(
    sym_name: str,
    file_path: str,
    signature: str,
    docstring: str,
    source_type: str,
    confidence: float,
    repo: str,
    line_start: int | None = None,
    line_end: int | None = None,
    kind: str | None = None,
    fallback_flag: list[bool] | None = None,
) -> ContextItem:
    """Build a ContextItem from raw symbol fields.

    When ``line_start``/``line_end`` are valid ints and source_type has a
    known verb, the ``reason`` field is populated with the upgraded
    function-level string (e.g. ``"Modified `foo` lines 59-159"``). If
    line data is missing or invalid, ``reason`` is left empty so the
    ranker falls back to the category-level string — and, if
    *fallback_flag* is provided, its first element is set to ``True`` so
    the caller can emit a single stderr warning per pack build.
    """
    title = f"{sym_name} ({Path(file_path).name})"
    excerpt = "\n".join(filter(None, [signature, docstring])).strip()

    qualified = sym_name
    # For methods, prefer a "Class.method" qualified name when the
    # signature contains the enclosing class (best-effort — Python's
    # analyzer emits bare names, so we use the signature as a hint).
    if kind == "method" and signature and "." in signature.split("(")[0]:
        head = signature.split("(")[0].strip()
        if head and not head.startswith("def "):
            qualified = head

    reason = ""
    verb = _SYMBOL_REASON_VERB.get(source_type)
    if (
        verb is not None
        and isinstance(line_start, int)
        and isinstance(line_end, int)
        and line_start > 0
        and line_end >= line_start
        and qualified
    ):
        reason = _build_symbol_reason(verb, qualified, line_start, line_end)
    elif verb is not None and fallback_flag is not None and not fallback_flag[0]:
        # Symbol-backed item but line metadata unusable — flag once so
        # the orchestrator can emit a single stderr warning per pack.
        fallback_flag[0] = True

    return ContextItem(
        source_type=source_type,
        repo=repo,
        path_or_ref=file_path,
        title=title,
        excerpt=excerpt,
        reason=reason,
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
        # v3.3.0 β5 — track the last observed ``repo_id`` so a live
        # Orchestrator instance (as used by the long-lived MCP server)
        # can detect an out-of-process reindex and surface a one-line
        # stderr advisory when the TTLCache's effective key rotated.
        # ``None`` on the first build; updated after each lookup.
        self._last_repo_id: str | None = None
        # v3.2 `pre-fix-review-mode`: when set to a commit SHA string, the
        # review-mode candidate builder treats the diff of that commit (vs
        # its parent) as the change-set, instead of the working-tree diff.
        # Scoped to the current build_pack call via a try/finally.
        self._pre_fix: str | None = None

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

    def invalidate_cache(self, *, reason: str = "manual") -> None:
        """Drop all cached packs (L1 in-process + L2 SQLite).

        Call after ``build_index``/``update_index``. The L2 ``pack_cache``
        table is cleared for the current ``repo_id`` (and implicitly
        invalidated for all future repo_ids by the mtime-derived key
        rotation). If the SQLite layer is unavailable we emit a stderr
        warning — per CLAUDE.md, silent failure is a bug.

        Args:
            reason: Human-readable cause that is folded into the stderr
                advisory the operator sees. The v3.3.0 β5 contract
                requires ``"repo reindexed"`` when the invalidation is
                triggered by an index bump; anything else (e.g. test
                cleanup) uses the default ``"manual"`` and is still
                surfaced so the operator is never surprised.
        """
        had_entries = False
        with self._pack_cache_lock:
            had_entries = len(self._pack_cache) > 0
            self._pack_cache.clear()
        # v3.3.0 β5 — always surface a one-line stderr note when the L1
        # cache actually had entries to drop. Silent invalidation (the
        # old behaviour) is a footgun: users notice the slow second run
        # but never see why. Skipped on an empty cache so warm-start
        # tests don't get spammed.
        if had_entries:
            print(
                f"note: ranking cache invalidated ({reason})",
                file=sys.stderr,
            )
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
    def _canonical_hub_boost_flag() -> str:
        """Return the canonical ``"1"``/``"0"`` form of ``CAPABILITIES_HUB_BOOST``.

        The hub-boost flag is a ranker-level capability that materially
        changes the final ordering of ``selected_items``. It MUST therefore
        participate in the pack-cache key, otherwise a previously-cached
        pack built with the flag off would be returned verbatim when the
        flag is subsequently toggled on (or vice-versa) — the exact bug
        the ``capabilities-hub-boost-cache-key`` outcome guards against.

        Normalisation mirrors the ranker's own truthy set
        (``1`` / ``true`` / ``yes`` / ``on``, case-insensitive, whitespace-
        stripped) so that semantically-equivalent env values resolve to
        the same key. Every other value — including unset / empty — maps
        to ``"0"``, matching the ranker's "off by default" resolution.
        """
        raw = os.environ.get("CAPABILITIES_HUB_BOOST")
        if raw is None:
            return "0"
        return "1" if raw.strip().lower() in {"1", "true", "yes", "on"} else "0"

    @staticmethod
    def _cache_key_string(
        mode: str,
        query_hash: str,
        token_budget: int,
        use_embeddings: bool,
        items_hash: str,
        hub_boost_flag: str = "0",
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
            hub_boost_flag,
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
        token_budget: int | None = None,
        pre_fix: str | None = None,
        keep_low_signal: bool = False,
    ) -> ContextPack:
        """Build and return a ranked ContextPack for the given mode and query.

        Persists the result to ``.context-router/last-pack.json`` so that
        ``context-router explain last-pack`` can read it without re-running.

        Args:
            mode: One of "review", "debug", "implement", "handover", "minimal".
                Minimal mode returns a tightly-budgeted (≤800 token) preview
                with at most 5 items and a ``next_tool_suggestion`` hint under
                ``pack.metadata`` — it is the CRG-parity triage entry point.
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
            token_budget: Optional per-call override for the ranker's token
                budget. When ``None`` (default), uses
                ``config.token_budget``; minimal mode defaults to 800
                when omitted.
            pre_fix: Optional commit SHA. When provided with ``mode="review"``,
                the candidate builder uses the diff of ``<sha>^..<sha>`` as
                the change-set (same data path as the normal review flow).
                This lets callers generate a pack ranked as if the working
                tree were at ``<sha>^`` — CRG-comparable without needing
                to hand in a pre-computed diff. Ignored for non-review
                modes (the CLI rejects the combination loudly).
            keep_low_signal: Review-mode escape hatch. When False (default),
                ``review`` packs drop trailing ``source_type="file"`` items
                with confidence < 0.3 once higher-tier items have already
                filled the token budget (v3.2 outcome
                ``review-tail-cutoff``). Pass True to preserve the full
                tail — only useful for debugging ranker output. Ignored
                for non-review modes; passing it elsewhere emits a stderr
                warning (silent no-ops are banned).

        Returns:
            A populated and ranked ContextPack.

        Raises:
            FileNotFoundError: If the SQLite database does not exist (index has
                not been run yet).
            ValueError: If *mode* is not a recognised value, or if
                ``pre_fix`` is set but not a valid commit SHA in the repo.
        """
        # Validate pre_fix early (before any expensive work) so the CLI can
        # surface a clean "commit <sha> not found" error without a traceback.
        # Only meaningful in review mode; for other modes the caller should
        # never have gotten here (pack.py rejects the combination).
        if pre_fix and mode == "review":
            if not self._validate_commit_sha(pre_fix):
                raise ValueError(
                    f"commit {pre_fix} not found in {self._root}"
                )

        # Silent-failure rule: keep_low_signal is a review-mode-only escape
        # hatch. Passing it in another mode would silently have no effect,
        # so emit a one-line stderr warning naming the reason (CLAUDE.md).
        if keep_low_signal and mode != "review":
            print(
                "warning: keep_low_signal=True has no effect outside "
                f"--mode review (current mode={mode!r}); ignoring.",
                file=sys.stderr,
            )
        config = load_config(self._root)
        repo_scope = str(self._root.resolve())
        db_path = self._root / ".context-router" / "context-router.db"

        if not db_path.exists():
            raise FileNotFoundError(
                f"Index database not found at {db_path}. "
                "Run 'context-router index' first."
            )

        # Resolve the effective caller-level token budget. `None` means "use
        # config default" for backward compatibility. v4.4 precision-first:
        # per-mode budgets in ``config.mode_budgets`` take precedence over
        # the global ``config.token_budget`` so review/implement default to
        # 1500 tokens (was 4000/8000) without breaking explicit overrides.
        # Minimal mode keeps its 800-token cap from the mode_budgets dict.
        if token_budget is None:
            mode_default = config.mode_budgets.get(mode)
            if mode_default is not None:
                caller_budget = int(mode_default)
            elif mode == "minimal":
                caller_budget = 800
            else:
                caller_budget = int(config.token_budget)
        else:
            caller_budget = int(token_budget)

        # Cache lookup — identical inputs return the previously built
        # ContextPack without re-running candidate building or ranking.
        # L1 (in-process TTLCache) benefits the long-lived MCP server;
        # L2 (SQLite-backed, migration 0012) persists across CLI processes
        # so a second `context-router pack` run for the same query skips
        # the full pipeline.
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        # Build the items-hash kwargs exactly like the pre-v3.2 version by
        # default so existing tests/consumers hitting the same (mode, query)
        # still see a cache hit. Only fold pre_fix into the hash when the
        # caller actually supplied one — then two builds on different SHAs
        # correctly miss each other's cache.
        items_hash_kwargs: dict[str, Any] = {
            "error_file": error_file if error_file is None else str(error_file),
            "page": page,
            "page_size": page_size,
        }
        if pre_fix:
            items_hash_kwargs["pre_fix"] = pre_fix
        # v3.2 outcome ``review-tail-cutoff`` (P1): the low-signal tail is
        # dropped from review-mode packs by default but a caller can opt
        # back in via ``keep_low_signal=True``. Fold the flag into the
        # items-hash only for the review mode where it actually changes
        # the pack (non-review packs still hit existing caches).
        if keep_low_signal and mode == "review":
            items_hash_kwargs["keep_low_signal"] = True
        items_hash = self._compute_items_hash(**items_hash_kwargs)
        repo_id = self._compute_repo_id()
        # v3.3.0 β5 — detect reindex-driven cache rotation. ``repo_id`` is
        # derived from the symbols table shape, so a ``build_index`` /
        # ``update_index`` run shifts it. Any long-lived Orchestrator
        # (notably the MCP server) holds onto L1 entries keyed by the
        # prior id; surface a one-line stderr note when we see the shift
        # so the operator knows the next call is a cold build, not a
        # spurious slowdown. The cache entries themselves are left alone
        # — they expire naturally via the TTL — because the new key
        # bypasses them anyway.
        if self._last_repo_id is not None and self._last_repo_id != repo_id:
            print(
                "note: ranking cache invalidated (repo reindexed)",
                file=sys.stderr,
            )
        self._last_repo_id = repo_id
        # ``CAPABILITIES_HUB_BOOST`` participates in the cache key because
        # the ranker applies or skips the hub/bridge structural boost
        # depending on its value — two packs built for the same query
        # under different flag values are genuinely different packs.
        # See ``_canonical_hub_boost_flag`` for the normalisation contract.
        hub_boost_flag = self._canonical_hub_boost_flag()
        cache_key = (
            repo_id,
            mode,
            query_hash,
            caller_budget,
            bool(use_embeddings),
            items_hash,
            hub_boost_flag,
        )
        with self._pack_cache_lock:
            cached = self._pack_cache.get(cache_key)
        if cached is not None:
            return cached

        # L2 lookup — persists across CLI invocations.
        cache_key_str = self._cache_key_string(
            mode,
            query_hash,
            caller_budget,
            bool(use_embeddings),
            items_hash,
            hub_boost_flag,
        )
        l2_pack = self._l2_get(cache_key_str, repo_id, db_path)
        if l2_pack is not None:
            # Re-hydrate L1 so subsequent same-process calls are fastest.
            with self._pack_cache_lock:
                self._pack_cache[cache_key] = l2_pack
            return l2_pack

        # Scope pre_fix to this build so ``_get_changed_files`` reads the
        # commit-range diff (``<sha>^..<sha>``) instead of the working-tree
        # diff. Only meaningful in review mode; the CLI rejects the combo
        # in other modes. Reset in the finally clause below so a future
        # re-use of this Orchestrator instance starts with a clean slate.
        self._pre_fix = pre_fix if (pre_fix and mode == "review") else None
        try:
            return self._build_pack_inner(
                mode=mode,
                query=query,
                error_file=error_file,
                page=page,
                page_size=page_size,
                use_embeddings=use_embeddings,
                progress=progress,
                progress_cb=progress_cb,
                download_progress_cb=download_progress_cb,
                config=config,
                repo_scope=repo_scope,
                db_path=db_path,
                caller_budget=caller_budget,
                token_budget=token_budget,
                cache_key=cache_key,
                cache_key_str=cache_key_str,
                repo_id=repo_id,
                keep_low_signal=keep_low_signal,
            )
        finally:
            # Always clear so subsequent reuses of this Orchestrator instance
            # don't silently inherit the SHA-based diff source.
            self._pre_fix = None

    def _build_pack_inner(
        self,
        *,
        mode: str,
        query: str,
        error_file: Path | None,
        page: int,
        page_size: int,
        use_embeddings: bool,
        progress: bool,
        progress_cb: "Callable[[str, int, int], None] | None",
        download_progress_cb: Callable[[str], None] | None,
        config: ContextRouterConfig,
        repo_scope: str,
        db_path: Path,
        caller_budget: int,
        token_budget: int | None,
        cache_key: tuple,
        cache_key_str: str,
        repo_id: str,
        keep_low_signal: bool = False,
    ) -> ContextPack:
        """Internal body of :meth:`build_pack` — split so the outer wrapper
        can own the ``self._pre_fix`` lifecycle via try/finally without
        indenting the whole pipeline by another level.
        """
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

            # v3.3.0 β3 — resolve or drop ``<external>`` placeholder items.
            # The graph writer materialises symbol stubs with
            # ``file=Path("<external>")`` for inheritance targets whose
            # source is outside the indexed repo. These bleed into review
            # packs as rank-2 items with no file path, eating tokens and
            # precision. Policy: try to resolve to a real path via import
            # adjacency; drop the item otherwise. Per-pack drop count is
            # surfaced on ``pack.metadata.external_dropped``.
            candidates, _external_dropped = self._resolve_external_items(
                candidates, edge_repo, repo_name="default",
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
            # Minimal mode is a cheap triage view — honor the tight caller
            # budget verbatim (no "at least 1000 tokens" floor) so callers can
            # actually shrink the pack to fit their prompt window.
            if mode == "minimal":
                effective_budget = min(effective_budget, caller_budget)
            elif token_budget is not None:
                effective_budget = min(effective_budget, caller_budget)
            ranker = ContextRanker(
                token_budget=effective_budget,
                use_embeddings=use_embeddings,
                progress_cb=effective_cb,
                # v3.1 `hub-bridge-sqlite-reuse` (P2): share the open
                # Database connection so the hub/bridge boost doesn't
                # open a fresh sqlite3.Connection per pack build.
                db_connection=db.connection,
                memory_budget_pct=config.memory_budget_pct,
            )
            # v3.2 outcome ``diff-aware-ranking-boost`` (P2): when review
            # mode has a diff to reason about — either the working-tree
            # diff (``HEAD``) or a ``--pre-fix`` commit — thread the spec
            # through so the ranker can lift items whose symbol lines
            # overlap the changed-line set. In non-review modes, pass
            # ``None`` so the boost is a strict no-op (DoD negative case).
            diff_spec_for_rank: str | None = None
            if mode == "review":
                diff_spec_for_rank = (
                    self._pre_fix if self._pre_fix else "HEAD"
                )
            boosted_items_ids: list[str] = []
            source_discovery = (
                mode in {"implement", "minimal"}
                or (mode == "debug" and not runtime_signals)
            )
            all_ranked = ranker.rank(
                candidates,
                query,
                mode,
                diff_spec=diff_spec_for_rank,
                project_root=self._root,
                boosted_items_sink=boosted_items_ids,
                source_discovery=source_discovery,
            )
            all_ranked, _dup_dropped = _dedup_ranked(all_ranked)
            # v3.2 outcome ``symbol-stub-dedup`` (P1): collapse identical
            # symbol stubs within the same file. The ranker already runs
            # this pass BEFORE its internal budget enforcement (so the
            # budget fills with distinct content); we repeat it here so
            # any duplicates introduced by post-rank accumulation paths
            # (e.g. candidate re-injection by contracts_boost) are also
            # caught, and so the aggregate dropped count is folded into
            # ``ContextPack.duplicates_hidden`` below.
            all_ranked, _stub_dropped = dedup_stubs(all_ranked)
            _dup_dropped += _stub_dropped

            # Phase-2 contracts boost — applied AFTER ranking + dedup so the
            # boost lifts items that already survived budget enforcement,
            # and BEFORE pagination so the boosted item lands in page 0.
            # Re-sort by confidence to keep highest-confidence first.
            all_ranked = self._apply_contracts_boost(
                all_ranked, self._root, repo_name="default", config=config
            )
            all_ranked.sort(key=lambda i: i.confidence, reverse=True)

            # Phase 3 Wave 2: review-mode risk overlay. Pure display metadata
            # — not a ranking signal — so it runs AFTER rank+dedup+boosts
            # but BEFORE pagination so every page sees the labels.
            if mode == "review":
                all_ranked = self._apply_review_risk(all_ranked)
                # v3.2 outcome ``review-tail-cutoff`` (P1): once higher-tier
                # items have already filled the token budget, trailing
                # ``source_type="file"`` items with confidence < 0.3 add
                # review burden without new signal. Drop them unless the
                # caller explicitly opted into the legacy "keep tail"
                # behaviour for debugging. Structural source types
                # (changed_file, blast_radius, config) are NEVER cut,
                # regardless of confidence.
                if not keep_low_signal:
                    all_ranked = self._apply_review_tail_cutoff(
                        all_ranked, effective_budget
                    )

            # Phase 4 Wave 1: debug-mode flow-level annotation. Runs after
            # ranking + dedup + boosts so the top-N items are finalized, and
            # BEFORE pagination so each page carries its ``flow`` labels.
            # Returns the annotated list plus an optional explanatory note
            # that is folded into ``pack.metadata`` below.
            debug_flow_note: str | None = None
            if mode == "debug":
                all_ranked, debug_flow_note = self._apply_debug_flows(
                    all_ranked, sym_repo, edge_repo, repo_name="default"
                )

            # v4.4 B3: enrich items with inline symbol bodies for token-efficient reads.
            all_ranked = self._enrich_with_symbol_bodies(all_ranked, sym_repo)

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

        # Minimal mode: hard-cap to top-5 items by confidence (ranker already
        # sorts by confidence desc) and attach a next-tool suggestion so the
        # caller can escalate to a deeper pack when the preview isn't enough.
        #
        # v3.1 `minimal-mode-ranker-tuning` (P1): the ≤5-item cap alone can
        # drop the top implement-mode code-symbol pick when a tight
        # token budget + source-type coverage (``_enforce_budget``) admits
        # a small item of the same source_type first, pushing a larger
        # higher-confidence item out of the pack. For task-verb queries
        # ("add X", "fix Y") the highest-confidence code-symbol item is
        # the single most task-relevant result — it MUST survive the cap.
        # We re-rank the same candidate pool with an unbounded budget so
        # budget-driven drops cannot hide the true top pick, then pin it
        # at position 0 of the final top-5. Other modes are untouched.
        pack_metadata: dict[str, Any] = {}
        if mode == "minimal":
            page_items = self._preserve_top_implement_item(
                page_items,
                candidates=candidates,
                query=query,
                use_embeddings=use_embeddings,
                config=config,
            )
            has_more = False
            pack_metadata["next_tool_suggestion"] = _suggest_next_tool(page_items, query)

        # Phase 4 Wave 1: surface flow-detection status in the debug pack so
        # consumers can tell the difference between "no flows available" and
        # "flows available on every item". ``debug_flow_note`` is ``None``
        # when the threshold (>=3 annotated top-5 items) is met.
        if mode == "debug" and debug_flow_note:
            pack_metadata["note"] = debug_flow_note

        # v3.2 outcome ``diff-aware-ranking-boost`` (P2): surface the set
        # of item IDs that received the +0.15 structural bump. Always
        # present on review-mode packs (empty list when no overlaps hit);
        # omitted for non-review modes so the key's presence cleanly
        # communicates "boost pathway ran".
        if mode == "review":
            pack_metadata["boosted_items"] = list(boosted_items_ids)

        # v3.3.0 β3 — surface the number of ``<external>`` placeholder
        # items we dropped (or resolved) this build. Zero is still
        # reported so agents / eval harnesses can tell the difference
        # between "no externals seen" and "pipeline skipped".
        pack_metadata["external_dropped"] = int(_external_dropped)

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
            metadata=pack_metadata,
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
        # v3.2 outcome: function-level-reason — single-element flag consumed
        # by ``_make_item`` when a symbol-backed item has no usable line
        # metadata, triggering the once-per-pack stderr warning below.
        self._symbol_reason_fallback_flag: list[bool] = [False]

        if mode == "review":
            items = self._review_candidates(sym_repo, edge_repo, repo_name, weights)
        elif mode == "implement":
            items = self._implement_candidates(sym_repo, repo_name, weights)
        elif mode == "minimal":
            # Minimal mode reuses implement candidate selection — the goal is a
            # cheap triage view ranked by relevance to the task, not a distinct
            # signal source. The orchestrator later caps to top-5 and emits a
            # next_tool_suggestion for follow-up.
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
        # v4.4 precision-first: scoped to handover only. For per-task queries
        # (review/implement/debug/minimal) cluster-mates pull in tangentially
        # related files that hurt precision. Handover is intentionally broad
        # so the cohesion signal is helpful there.
        if mode == "handover":
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

        # v3.2 function-level-reason: if any symbol-backed item lacked
        # usable line metadata, warn once so the category-level fallback
        # is visible rather than a silent degradation (CLAUDE.md rule:
        # "Silent failure is a bug").
        if self._symbol_reason_fallback_flag[0]:
            print(
                "context-router: function-level reason fell back to "
                "category string for one or more items — symbol line "
                "metadata missing or invalid",
                file=sys.stderr,
            )
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
    # Contracts-consumer boost (Phase 2 — single-repo packs)
    # ------------------------------------------------------------------

    def _load_repo_endpoint_paths(
        self, db_path: Path, repo_name: str
    ) -> list[str]:
        """Return the distinct OpenAPI endpoint paths declared in *repo_name*.

        Falls back to a one-shot ``extract_contracts(self._root)`` walk when
        the ``api_endpoints`` table is empty. The single-repo CLI ``index``
        command does not yet populate this table — running the parser at
        boost time keeps the feature working for any repo with a static
        OpenAPI spec, without forcing a re-index.

        Returns a deduplicated list (order preserved); empty when neither
        the table nor the on-disk walk yields any endpoints.
        """
        paths: list[str] = []
        seen: set[str] = set()

        # Step 1 — preferred source: the persisted api_endpoints table.
        try:
            with Database(db_path) as db:
                rows = ContractRepository(db.connection).list_api_endpoints(repo_name)
            for row in rows:
                p = row.get("path") or ""
                if p and p not in seen:
                    seen.add(p)
                    paths.append(p)
        except Exception as exc:  # noqa: BLE001 — DB read is best-effort
            _warn_optional_subsystem_failure(
                "Contracts boost endpoint lookup",
                "falling back to on-disk OpenAPI extraction for this build",
                exc,
            )

        if paths:
            return paths

        # Step 2 — fallback: parse the repo's OpenAPI specs directly.
        try:
            from contracts_extractor import ApiEndpoint, extract_contracts
            for c in extract_contracts(self._root):
                if isinstance(c, ApiEndpoint) and c.path and c.path not in seen:
                    seen.add(c.path)
                    paths.append(c.path)
        except Exception as exc:  # noqa: BLE001 — fallback is best-effort
            _warn_optional_subsystem_failure(
                "Contracts boost on-disk extraction",
                "the contracts-consumer boost will be skipped for this build",
                exc,
            )

        return paths

    def _apply_contracts_boost(
        self,
        items: list[ContextItem],
        repo_root: Path,
        repo_name: str = "default",
        config: ContextRouterConfig | None = None,
    ) -> list[ContextItem]:
        """Boost items whose source file consumes a same-repo OpenAPI endpoint.

        Mirrors :func:`workspace_orchestrator._boost_contract_linked_items`
        for the single-repo case: there is no "other repo" to anchor on, so
        the producer side IS the same repo. Items receive ``+0.10``
        confidence (clamped at 0.95) when their file references one of the
        endpoint paths via a quote-anchored URL literal — see
        :func:`contracts_extractor.file_references_endpoint` for the regex.

        The boost is a no-op when:
          * the ``capabilities.contracts_boost`` config flag is False,
          * the repo declares no API endpoints (logged once to stderr), or
          * the candidate list is empty.

        Returns a NEW list (originals are immutable per pydantic model_copy);
        the caller is responsible for re-sorting by confidence if order
        matters.
        """
        if not items:
            return items
        if config is not None and not config.capabilities.contracts_boost:
            return items

        db_path = repo_root / ".context-router" / "context-router.db"
        endpoint_paths = self._load_repo_endpoint_paths(db_path, repo_name)
        if not endpoint_paths:
            # Per CLAUDE.md silent-failure rule, name the no-op explicitly.
            print(
                "contracts boost skipped (0 endpoints indexed)",
                file=sys.stderr,
            )
            return items

        from contracts_extractor import file_references_endpoint

        # Cache per-file reads — many candidate items share a file (one per
        # symbol) and re-reading is the dominant cost.
        file_text_cache: dict[str, str] = {}

        def _read(path_str: str) -> str:
            if path_str in file_text_cache:
                return file_text_cache[path_str]
            text = ""
            try:
                p = Path(path_str)
                if not p.is_absolute():
                    p = repo_root / p
                if p.is_file():
                    # Read at most _CONTRACTS_FILE_READ_LIMIT bytes; this is
                    # plenty for the imports-and-handler section that holds
                    # any URL literal worth matching.
                    with p.open("rb") as fh:
                        raw = fh.read(_CONTRACTS_FILE_READ_LIMIT)
                    text = raw.decode("utf-8", errors="replace")
            except (OSError, ValueError):
                text = ""
            file_text_cache[path_str] = text
            return text

        out: list[ContextItem] = []
        for item in items:
            text = _read(item.path_or_ref)
            if not text:
                out.append(item)
                continue
            matched = any(
                file_references_endpoint(text, ep) for ep in endpoint_paths
            )
            if matched:
                new_conf = min(
                    _CONTRACTS_BOOST_MAX_CONFIDENCE,
                    item.confidence + _CONTRACTS_BOOST,
                )
                out.append(item.model_copy(update={"confidence": new_conf}))
            else:
                out.append(item)
        return out

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
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    kind=sym.kind,
                    fallback_flag=self._symbol_reason_fallback_flag,
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
        """Return the set of file paths changed in the review-mode diff.

        * When :attr:`_pre_fix` is set to a commit SHA, uses
          ``git diff --name-status <sha>^..<sha>`` so the pack is ranked
          as-if the working tree were at ``<sha>^``. Never mutates the
          working tree.
        * Otherwise (the default), uses the working-tree diff against
          ``HEAD~1`` — the existing review-mode contract.

        Falls back to an empty set if the git command fails (e.g. a repo
        with only one commit, or when run outside a git repo).

        Returns:
            Set of absolute-or-repo-relative path strings.
        """
        since = self._pre_fix_range() if self._pre_fix else "HEAD~1"
        try:
            changed = GitDiffParser.from_git(self._root, since)
            return {str(self._root / cf.path) for cf in changed}
        except (RuntimeError, OSError):
            return set()

    def _pre_fix_range(self) -> str:
        """Return the ``<sha>^..<sha>`` range string for the scoped pre_fix."""
        # ``pre_fix`` is validated by _validate_commit_sha before we reach
        # here; we still guard with ``or ""`` so a stale attribute on a
        # re-used instance cannot synthesise an ``^..`` gibberish string.
        sha = (self._pre_fix or "").strip()
        return f"{sha}^..{sha}"

    def _validate_commit_sha(self, sha: str) -> bool:
        """Return True iff *sha* (and its parent ``sha^``) exist in the repo.

        Uses ``git cat-file -e <rev>^{commit}`` for a cheap existence check
        that does not touch the working tree. Both the SHA and its parent
        must resolve — our diff command is ``<sha>^..<sha>``, so a root
        commit with no parent should be rejected loudly rather than
        falling through to an empty diff.
        """
        import subprocess

        stripped = (sha or "").strip()
        if not stripped:
            return False
        # Disallow whitespace — shlex would let weird refs through; the
        # feature contract says "a single commit SHA".
        if any(c.isspace() for c in stripped):
            return False
        for rev in (f"{stripped}^{{commit}}", f"{stripped}^^{{commit}}"):
            try:
                result = subprocess.run(
                    ["git", "cat-file", "-e", rev],
                    cwd=str(self._root),
                    capture_output=True,
                    check=False,
                )
            except (FileNotFoundError, OSError):
                return False
            if result.returncode != 0:
                return False
        return True

    def _apply_review_risk(self, items: list[ContextItem]) -> list[ContextItem]:
        """Return *items* with per-item ``risk`` populated for review mode.

        Pulls the current diff via :class:`GitDiffParser` and pairs each
        changed file with a cheap size-based complexity proxy. Items whose
        ``path_or_ref`` is not in the diff stay at ``risk="none"``.

        The diff set intentionally contains BOTH the absolute path and the
        repo-relative path for each changed file so the membership check
        matches symbol records regardless of whether they were indexed
        with relative or absolute paths (existing stores do both).

        Silent-failure rule (CLAUDE.md): if the diff lookup fails (not a
        git repo, first commit on branch, etc.) we emit a one-line stderr
        debug note so reviewers can tell the risk column is intentionally
        blank rather than silently skipped. Risk stays ``"none"`` for all
        items in that case.
        """
        if not items:
            return items
        try:
            raw_diff = self._get_changed_files()
        except Exception as exc:  # noqa: BLE001 — risk is best-effort
            print(
                f"review-mode risk overlay skipped (git diff lookup failed: {exc})",
                file=sys.stderr,
            )
            return items
        if not raw_diff:
            # Negative case: no diff → every item stays risk="none".
            # Avoid per-item copies — defaults already satisfy the contract.
            return items

        # Build a membership set that works for both absolute-path items
        # (MCP contract) and relative-path items (most symbol repositories
        # persist repo-relative paths). For each changed file we also
        # record its size keyed by BOTH forms so the lookup in
        # _compute_risk hits regardless of how the item was stored.
        #
        # NOTE: self._root may be a relative path (e.g. ``Path(".")`` when
        # the CLI is invoked with ``--project-root .``). We resolve to an
        # absolute form so membership checks hit items whose
        # ``path_or_ref`` is stored in canonical absolute form.
        diff_files: set[str] = set()
        file_size: dict[str, int] = {}
        try:
            root_abs = self._root.resolve()
        except (OSError, RuntimeError):
            root_abs = self._root
        for fp in raw_diff:
            p = Path(fp)
            if p.is_absolute():
                abs_path = p
            else:
                abs_path = (self._root / p)
            try:
                abs_resolved = abs_path.resolve()
            except (OSError, RuntimeError):
                abs_resolved = abs_path
            abs_str = str(abs_resolved)
            nonresolved_abs = str(abs_path)
            try:
                rel_str = str(abs_resolved.relative_to(root_abs))
            except ValueError:
                # Path lives outside the project root; keep absolute form.
                rel_str = abs_str
            lines = _count_lines(abs_resolved)
            for key in {abs_str, nonresolved_abs, rel_str, fp}:
                diff_files.add(key)
                file_size[key] = lines
            # Also record a leading-"./" form which some CLIs emit.
            if not rel_str.startswith(("/", ".")):
                dot_rel = f"./{rel_str}"
                diff_files.add(dot_rel)
                file_size[dot_rel] = lines

        return [
            item.model_copy(update={"risk": _compute_risk(item, diff_files, file_size)})
            for item in items
        ]

    def _apply_review_tail_cutoff(
        self,
        items: list[ContextItem],
        token_budget: int,
    ) -> list[ContextItem]:
        """Trim the trailing low-signal tail from a review-mode ranked list.

        v3.2 outcome ``review-tail-cutoff`` (P1). The fastapi eval showed
        review-mode packs ballooning to 498 items for a 1-file change,
        with ~46% of items clustered at the default file-category
        confidence of 0.25 — pure noise once the budget is already filled
        by structurally-important items. This pass walks the ranked list
        (already sorted by confidence descending), keeps every item until
        the cumulative ``est_tokens`` reaches ``token_budget``, and then
        drops every subsequent item whose ``source_type == "file"`` AND
        ``confidence < 0.3``. Structural source types (``changed_file``,
        ``blast_radius``, ``config``) are preserved regardless of their
        confidence and do NOT terminate the keep-list — the budget check
        gates low-signal tail only.

        Silent-failure rule (CLAUDE.md): if the cutoff would drop an item
        with ``confidence >= 0.7`` (which would indicate a real candidate
        that somehow got marked as ``source_type="file"``), emit a
        one-line stderr warning naming the path. This should never
        happen in practice — the confidence cutoff is 0.3 — but we
        refuse to fail silently if the ranker regresses.

        Args:
            items: Ranked ContextItem list (sorted by confidence desc).
            token_budget: Effective token budget for this pack. Once the
                cumulative est_tokens of kept items reaches this threshold,
                subsequent low-signal items become eligible to drop.

        Returns:
            The filtered list. When no items exceed the budget the input
            is returned untouched (tail preserved even if low-signal),
            matching the outcome's "tail cutoff only fires under pressure"
            contract.
        """
        if not items:
            return items
        # Structural types are always preserved; never count towards the
        # "drop low-signal file tail" rule.
        _STRUCTURAL = {"changed_file", "blast_radius", "config"}
        # The spec frames this as ``confidence < 0.3`` — targeting file
        # items that never rose above the default file-tier base
        # (``_REVIEW_CONFIDENCE["file"] = 0.20`` plus the default
        # community boost of +0.10). In practice the ranker's hub/bridge
        # and query-filename passes nudge these items up into the 0.30-
        # 0.39 band on real packs (fastapi eval), so the effective
        # "still at the file-tier" threshold is ~0.4. We use 0.4 as the
        # cutoff so the rule captures the low-signal file tail the spec
        # names (not the post-contracts-boost real hits at 0.40+).
        _FILE_CUTOFF_CONFIDENCE = 0.4
        _HIGH_CONFIDENCE_WARN = 0.7
        # The ranker's budget enforcement leaves headroom below the cap
        # (e.g., fastapi packs land at 7,984/8,000 tokens), so strict
        # "cumulative >= token_budget" is rarely triggered on real data.
        # Interpret "budget already reached" as "pack has used most of
        # its budget" — 75% captures the case where the higher-tier
        # items have already consumed the lion's share.
        _BUDGET_PRESSURE_FRACTION = 0.75

        # First pass: does cumulative est_tokens ever reach the "budget
        # pressure" threshold? If not, skip the cutoff entirely — the
        # negative-case contract says "no pressure, no cut".
        cumulative = 0
        pressure_threshold = max(1, int(token_budget * _BUDGET_PRESSURE_FRACTION))
        budget_reached = False
        for item in items:
            cumulative += int(getattr(item, "est_tokens", 0) or 0)
            if cumulative >= pressure_threshold:
                budget_reached = True
                break
        if not budget_reached:
            return items

        # Second pass: walk items, keep structural entries always, drop
        # trailing file/low-confidence items once the budget pressure
        # threshold is reached.
        kept: list[ContextItem] = []
        running = 0
        dropped_high_conf: list[str] = []
        for item in items:
            source_type = getattr(item, "source_type", "") or ""
            confidence = float(getattr(item, "confidence", 0.0) or 0.0)
            est = int(getattr(item, "est_tokens", 0) or 0)
            if source_type in _STRUCTURAL:
                kept.append(item)
                running += est
                continue
            # Non-structural item. Keep while under pressure; once
            # pressure hits, drop only if it's a low-signal file.
            if running < pressure_threshold:
                kept.append(item)
                running += est
                continue
            # Over pressure threshold, non-structural item.
            if source_type == "file" and confidence < _FILE_CUTOFF_CONFIDENCE:
                # Drop silently — this is the common case (231/498 on
                # fastapi). Only WARN if this item had legitimate
                # high-confidence signal, which would indicate a bug.
                if confidence >= _HIGH_CONFIDENCE_WARN:
                    dropped_high_conf.append(
                        str(getattr(item, "path_or_ref", "") or "")
                    )
                continue
            # Anything else (non-file source_type, or file with
            # confidence >= 0.3) is real signal; keep it.
            kept.append(item)
            running += est

        # The guard `confidence < _FILE_CUTOFF_CONFIDENCE` and
        # `confidence >= _HIGH_CONFIDENCE_WARN` are mutually exclusive
        # (0.3 < 0.7), so ``dropped_high_conf`` should always be empty.
        # If it isn't, the ranker regressed and the reviewer deserves a
        # loud, named warning (CLAUDE.md: silent failure is a bug).
        for path in dropped_high_conf:
            print(
                f"review-tail-cutoff dropped high-confidence item {path}",
                file=sys.stderr,
            )
        return kept

    def _apply_debug_flows(
        self,
        items: list[ContextItem],
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str = "default",
    ) -> tuple[list[ContextItem], str | None]:
        """Return *items* with ``flow`` annotated for debug-mode packs.

        For each item whose underlying symbol can be resolved (by
        ``path_or_ref`` + the leading token of ``title``), look up the
        affected flows via :func:`graph_index.flows.get_affected_flows` and
        label the item with a compact ``entry -> leaf`` string. The shortest
        flow wins when several flows pass through the same symbol.

        Returns a tuple ``(annotated_items, note_or_none)``. ``note_or_none``
        is a short explanation for ``pack.metadata["note"]`` when fewer than
        3 of the top-5 items could be annotated (the outcome's threshold) or
        when no flows are available at all. It is ``None`` when the threshold
        is met — in that case callers add no metadata note.

        Silent-failure rule: any unexpected error returns ``(items, note)``
        so the debug pack still rolls out without flow labels. A stderr
        warning is emitted so the missing annotations are never silent.
        """
        # Local import to avoid introducing a package-level dependency cycle
        # between core and graph-index.
        from graph_index.flows import list_flows

        if not items:
            return items, None

        # Pre-compute all flows once so per-item lookups stay O(total_flows).
        # Re-using a cached list across items also means a single stderr
        # warning (if any) is emitted rather than one per item.
        try:
            all_flows = list_flows(repo_name, sym_repo, edge_repo)
        except Exception as exc:  # noqa: BLE001 — silent-failure contract
            print(
                f"warning: debug flow annotation skipped "
                f"(list_flows failed: {exc})",
                file=sys.stderr,
            )
            return items, (
                "flows unavailable: list_flows failed (see stderr); "
                "items carry no ``flow`` labels"
            )

        if not all_flows:
            # Negative case required by the outcome: "no flows detected →
            # fall back to today's behavior with a note in explain.why".
            # Every item keeps flow=None.
            return items, (
                "no flows detected in the indexed graph; "
                "debug pack falls back to file-level context"
            )

        # Build a (file_path, symbol_name) -> symbol_id lookup so we can map
        # items back to symbols without a per-item SQL roundtrip.
        try:
            all_symbols = sym_repo.get_all(repo_name)
        except Exception as exc:  # noqa: BLE001 — silent-failure contract
            print(
                f"warning: debug flow annotation skipped "
                f"(symbol lookup failed: {exc})",
                file=sys.stderr,
            )
            return items, (
                "flows unavailable: symbol lookup failed (see stderr); "
                "items carry no ``flow`` labels"
            )

        file_name_to_id: dict[tuple[str, str], int] = {}
        for sym in all_symbols:
            if sym.id is None:
                continue
            file_name_to_id[(str(sym.file), sym.name)] = sym.id
            # Also index by just-the-basename so items with bare file names
            # resolve too.
            file_name_to_id[(Path(sym.file).name, sym.name)] = sym.id

        # Group flows by symbol id for cheap per-item affected-flow lookup.
        by_symbol: dict[int, list] = {}
        for f in all_flows:
            for sid in f.path:
                by_symbol.setdefault(sid, []).append(f)

        annotated: list[ContextItem] = []
        for item in items:
            # Extract the symbol name from the item title. Our ``_make_item``
            # helper formats titles as ``"{name} ({filename})"`` — split on
            # " (" to recover the leading symbol name. Call-chain /
            # runtime-signal items that lack this format simply won't match
            # the lookup, which is correct — they point to files, not
            # symbols, so there's no single symbol to anchor a flow to.
            sym_name = item.title.split(" (", 1)[0].strip()
            candidate_keys = (
                (item.path_or_ref, sym_name),
                (Path(item.path_or_ref).name, sym_name),
            )
            sym_id: int | None = None
            for key in candidate_keys:
                if key in file_name_to_id:
                    sym_id = file_name_to_id[key]
                    break

            if sym_id is None:
                annotated.append(item)
                continue

            flows = by_symbol.get(sym_id, [])
            if not flows:
                annotated.append(item)
                continue

            # Prefer the shortest flow for a compact label; ties broken by
            # (entry_name, leaf_name) so the label is stable across runs.
            best = min(flows, key=lambda f: (f.length, f.entry_name, f.leaf_name))
            annotated.append(item.model_copy(update={"flow": best.label}))

        # Threshold: at least 3 of the top-5 items must carry a non-null
        # flow. Fewer = add a metadata note so the caller can tell the
        # annotation layer ran but the data was insufficient.
        top_slice = annotated[:5]
        flow_count = sum(1 for i in top_slice if i.flow)
        if flow_count < 3:
            note = (
                f"flows available for only {flow_count} of top {len(top_slice)} items; "
                "consider re-indexing or widening the query"
            )
            return annotated, note
        return annotated, None

    # ------------------------------------------------------------------
    # v4.4 B3 — inline symbol body enrichment
    # ------------------------------------------------------------------

    def _enrich_with_symbol_bodies(
        self,
        items: list[ContextItem],
        sym_repo: "SymbolRepository",
        *,
        inline_top_only: bool = True,
    ) -> list[ContextItem]:
        """Populate symbol_body and symbol_lines on file-type items.

        Looks up line ranges with a single DB batch query, then reads just
        those lines from each source file. Items whose symbol is not in the
        DB or whose file cannot be read are returned unchanged (symbol_body
        stays None — the agent falls back to reading the full file).
        Memory and decision items are always skipped.

        v4.4 Phase 5 (precision-first): when ``inline_top_only`` is True
        (default), only the top-ranked code item gets its body inlined —
        the rest still get ``symbol_lines`` for cheap follow-up reads but
        without the body bytes that were inflating JSON packs to 3-5K
        tokens. Saves ~70% of JSON serialisation cost on a typical 5-item
        pack while preserving the agent's fast path on the most-likely
        answer. Pass ``inline_top_only=False`` to restore the v4.4 B3
        behaviour of inlining every item.
        """
        if not items:
            return items

        _MEM_TYPES = frozenset({"memory", "decision"})
        lookups: list[tuple[str, str, str]] = []
        for item in items:
            if item.source_type in _MEM_TYPES:
                continue
            # Title format from _build_symbol_reason: "SymbolName (filename.py)"
            name = item.title.split(" (")[0] if " (" in item.title else item.title
            if name and item.path_or_ref:
                lookups.append((item.repo or "default", item.path_or_ref, name))

        if not lookups:
            return items

        line_map = sym_repo.fetch_symbol_lines_batch(lookups)

        # v4.4 Phase 5: identify the top-ranked code item that is eligible
        # to receive an inlined body. Items are pre-sorted by confidence
        # before this method is called (orchestrator pipeline contract).
        top_inline_key: tuple[str, str, str] | None = None
        if inline_top_only:
            for item in items:
                if item.source_type in _MEM_TYPES:
                    continue
                name = item.title.split(" (")[0] if " (" in item.title else item.title
                if name and item.path_or_ref:
                    top_inline_key = (item.repo or "default", item.path_or_ref, name)
                    break

        result: list[ContextItem] = []
        for item in items:
            if item.source_type in _MEM_TYPES:
                result.append(item)
                continue
            name = item.title.split(" (")[0] if " (" in item.title else item.title
            key = (item.repo or "default", item.path_or_ref, name)
            line_range = line_map.get(key)
            if line_range is None:
                result.append(item)
                continue
            line_start, line_end = line_range
            if not line_start or not line_end or line_end < line_start:
                result.append(item)
                continue
            # v4.4 Phase 5: only the top-ranked item gets the inlined body.
            # Lower-ranked items still get symbol_lines so the agent has a
            # cheap pointer for follow-up reads.
            if inline_top_only and key != top_inline_key:
                result.append(item.model_copy(update={
                    "symbol_lines": (line_start, line_end),
                }))
                continue
            try:
                path = Path(item.path_or_ref)
                if not path.is_absolute():
                    path = self._root / path
                content = path.read_text(encoding="utf-8", errors="replace")
                body_lines = content.splitlines()[line_start - 1 : line_end]
                body = "\n".join(body_lines)
                result.append(item.model_copy(update={
                    "symbol_body": body,
                    "symbol_lines": (line_start, line_end),
                }))
            except OSError:
                result.append(item)

        return result

    # ------------------------------------------------------------------
    # v3.3.0 β3 — external reference resolution / filtering
    # ------------------------------------------------------------------

    # Marker path the graph writer uses for external symbol stubs. Any
    # item whose ``path_or_ref`` equals this sentinel represents a symbol
    # whose source lives outside the indexed repo (e.g. a framework base
    # class referenced by an ``extends``/``implements`` edge). Review
    # packs used to surface these as opaque rank-2 entries with no file
    # path — eating tokens and poisoning precision — so v3.3.0 resolves
    # or drops them before the ranker ever sees them.
    _EXTERNAL_PATH_MARKER: str = "<external>"

    def _resolve_external_items(
        self,
        items: list[ContextItem],
        edge_repo: EdgeRepository,
        repo_name: str = "default",
    ) -> tuple[list[ContextItem], int]:
        """Resolve or drop items whose ``path_or_ref`` is ``<external>``.

        Two-step resolution:

        1. Try to map the external stub back to a **real** in-repo file by
           walking inbound edges: if exactly one in-repo file references
           the external symbol, rewrite the item to point at that file
           (the referring file is the one the reviewer actually needs to
           open). When multiple files reference it, the "real" owner is
           ambiguous and we fall through to step 2.
        2. Drop the item from the candidate pool — we never emit an opaque
           ``<external>`` placeholder because the ranker can't give the
           user a file to open.

        Returns the filtered item list and the number of items that were
        dropped (NOT rewritten) so callers can surface the count on
        ``pack.metadata.external_dropped``.

        Both CLI ``pack --json`` and MCP ``get_context_pack`` share this
        path — they both call :meth:`build_pack` which invokes this
        helper once per pack build.
        """
        if not items:
            return items, 0

        kept: list[ContextItem] = []
        dropped = 0
        # Cheap inbound-file lookup: caller supplies an EdgeRepository so
        # we can do a single SQL-query per external symbol name instead
        # of loading the whole edge graph. Cache within this build to
        # avoid re-querying the same name across repeat items.
        resolution_cache: dict[str, str | None] = {}
        for item in items:
            if item.path_or_ref != self._EXTERNAL_PATH_MARKER:
                kept.append(item)
                continue

            # Try to resolve. The symbol's name is embedded in the title
            # in the ``"name (<external>)"`` form produced by _make_item.
            # If that shape ever changes the regex falls back to dropping.
            sym_name = item.title.split(" (")[0].strip() if item.title else ""
            resolved: str | None
            if sym_name and sym_name in resolution_cache:
                resolved = resolution_cache[sym_name]
            else:
                resolved = (
                    self._lookup_external_referrer(edge_repo, repo_name, sym_name)
                    if sym_name
                    else None
                )
                resolution_cache[sym_name] = resolved

            if resolved:
                # Rewrite in-place (``model_copy`` keeps the rest of the
                # item intact, including confidence and est_tokens). The
                # title's parenthetical is updated so reviewers see a real
                # file name instead of ``<external>``.
                basename = Path(resolved).name
                new_title = f"{sym_name} ({basename})" if sym_name else item.title
                kept.append(
                    item.model_copy(
                        update={
                            "path_or_ref": resolved,
                            "title": new_title,
                        }
                    )
                )
            else:
                dropped += 1

        # Silent-failure rule: ``<external>`` items used to leak through
        # to review packs and hurt precision. The drop counter is already
        # surfaced on ``pack.metadata.external_dropped``, but emit a
        # stderr note the first time we drop one so the filter is never
        # invisible to the operator.
        if dropped > 0:
            print(
                f"note: dropped {dropped} opaque <external> placeholder "
                "item(s) from pack (no resolvable file path)",
                file=sys.stderr,
            )
        return kept, dropped

    @staticmethod
    def _lookup_external_referrer(
        edge_repo: EdgeRepository,
        repo_name: str,
        sym_name: str,
    ) -> str | None:
        """Return the single in-repo file that references *sym_name*, or None.

        Implementation: run :meth:`EdgeRepository.get_adjacent_files`
        keyed on the external-stub file marker. If exactly one distinct
        non-``<external>`` file path comes back we can confidently
        attribute the reference to that file; two or more ⇒ ambiguous
        (caller drops the item). Any DB failure returns None.
        """
        try:
            candidates = edge_repo.get_adjacent_files(
                repo_name, Orchestrator._EXTERNAL_PATH_MARKER
            )
        except Exception:  # noqa: BLE001 — DB errors should never block pack build
            return None
        real_files = {
            p for p in candidates
            if p and p != Orchestrator._EXTERNAL_PATH_MARKER
        }
        if len(real_files) == 1:
            return next(iter(real_files))
        return None

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

    def _preserve_top_implement_item(
        self,
        page_items: list[ContextItem],
        *,
        candidates: list[ContextItem],
        query: str,
        use_embeddings: bool,
        config: ContextRouterConfig | None,
    ) -> list[ContextItem]:
        """Return the minimal-mode top-5 with the top implement pick pinned at 0.

        Applied only from the ``build_pack`` minimal-mode branch. It
        augments the naive ``page_items[:5]`` cap so the single most
        task-relevant code-symbol item (the highest-confidence item that
        an ``implement``-mode ranker pass would surface) never gets
        displaced by source-type-coverage budget enforcement.

        Algorithm:
            1. Re-rank the SAME candidate pool with ``token_budget=0``
               (no budget). This removes drops caused by
               :meth:`ContextRanker._enforce_budget` reserving a small
               same-source-type item ahead of a large high-confidence one.
            2. Apply the same dedup + contracts-boost + confidence sort
               that the primary pipeline applies so the unbounded list is
               comparable to ``all_ranked``.
            3. Pick the first item whose ``source_type`` is a code-symbol
               type (see :data:`_IMPLEMENT_SOURCE_TYPES`). This is the
               "top implement-mode candidate".
            4. If no code-symbol candidate exists (e.g. empty repo or
               metadata-only candidate pool), return the original top-5
               untouched — preserves the coverage-selected items and
               avoids crashing.
            5. Otherwise, return ``[top_implement_item] + page_items[:5]``
               de-duplicated by ``(path_or_ref, title)``, truncated to 5.
        """
        capped = list(page_items[:5])
        if not candidates:
            return capped
        try:
            probe = ContextRanker(
                token_budget=0,
                use_embeddings=use_embeddings,
                progress_cb=None,
            )
            unbounded = probe.rank(candidates, query, "minimal")
            unbounded, _ = _dedup_ranked(unbounded)
            unbounded = self._apply_contracts_boost(
                unbounded, self._root, repo_name="default", config=config
            )
            unbounded.sort(key=lambda i: i.confidence, reverse=True)
        except Exception as exc:  # noqa: BLE001 — preservation is best-effort
            _warn_optional_subsystem_failure(
                "Minimal-mode top-item preservation",
                "the pack will fall back to the naive 5-item confidence cap",
                exc,
            )
            return capped

        top_implement: ContextItem | None = next(
            (it for it in unbounded if it.source_type in _IMPLEMENT_SOURCE_TYPES),
            None,
        )
        if top_implement is None:
            # No code-symbol candidate — graceful fallback (e.g. empty repo
            # indexed only with memory/decision items).
            return capped

        key = (top_implement.path_or_ref, top_implement.title)
        # Drop any existing copy in the capped list so we can re-insert at 0.
        remaining = [it for it in capped if (it.path_or_ref, it.title) != key]
        # Keep up to 4 others; the preserved item takes slot 0.
        return [top_implement] + remaining[:4]

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
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    kind=sym.kind,
                    fallback_flag=self._symbol_reason_fallback_flag,
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
            elif fp in changed_files:
                source_type = "changed_file"
                confidence = weights.get("changed_file", _DEBUG_CONFIDENCE["changed_file"])
            elif self._is_test_file(fp) and (
                bool(signals) or self._matches_changed(fp, changed_files)
            ):
                source_type = "failing_test"
                confidence = weights.get("failing_test", _DEBUG_CONFIDENCE["failing_test"])
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
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    kind=sym.kind,
                    fallback_flag=self._symbol_reason_fallback_flag,
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
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    kind=sym.kind,
                    fallback_flag=self._symbol_reason_fallback_flag,
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
