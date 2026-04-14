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

import re
from pathlib import Path

from contracts.config import ContextRouterConfig, load_config
from contracts.models import ContextItem, ContextPack, RuntimeSignal
from graph_index.git_diff import GitDiffParser
from ranking import ContextRanker, estimate_tokens
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Fixed overhead per ContextItem in JSON transport: UUID (9), source_type (5),
# repo (5), path (10), reason (5), freshness ISO datetime (10), tags (5) ≈ 40.
_METADATA_OVERHEAD_TOKENS: int = 40


def _estimate_item_tokens(title: str, excerpt: str) -> int:
    """Estimate token cost of a ContextItem including JSON metadata overhead."""
    return estimate_tokens(title + " " + excerpt) + _METADATA_OVERHEAD_TOKENS

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

    def __init__(self, project_root: Path | None = None) -> None:
        """Initialise the orchestrator.

        Args:
            project_root: Optional explicit project root path.
        """
        self._root = project_root or _find_project_root(Path.cwd())

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

        Returns:
            A populated and ranked ContextPack.

        Raises:
            FileNotFoundError: If the SQLite database does not exist (index has
                not been run yet).
            ValueError: If *mode* is not a recognised value.
        """
        config = load_config(self._root)
        db_path = self._root / ".context-router" / "context-router.db"

        if not db_path.exists():
            raise FileNotFoundError(
                f"Index database not found at {db_path}. "
                "Run 'context-router index' first."
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
                from memory.store import ObservationStore
                sig_repo = RuntimeSignalRepository(db.connection)
                obs_store = ObservationStore(db)
                for sig in runtime_signals:
                    try:
                        sig_repo.add(sig)
                    except Exception:  # noqa: BLE001
                        pass  # best-effort
                    # Look up past signals with the same error_hash
                    if sig.error_hash:
                        try:
                            past = sig_repo.find_by_error_hash(sig.error_hash)
                            for ps in past[1:]:  # skip the one we just inserted
                                for p in ps.paths:
                                    past_debug_files.add(str(p))
                                    past_debug_files.add(p.name)
                        except Exception:  # noqa: BLE001
                            pass

            # Phase 6: load feedback-based confidence adjustments
            try:
                from storage_sqlite.repositories import PackFeedbackRepository
                feedback_adjustments = PackFeedbackRepository(db.connection).get_file_adjustments()
            except Exception:  # noqa: BLE001
                feedback_adjustments = {}

            candidates = self._build_candidates(
                mode, sym_repo, edge_repo, runtime_signals=runtime_signals,
                past_debug_files=past_debug_files,
                feedback_adjustments=feedback_adjustments,
            )

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
        ranker = ContextRanker(token_budget=effective_budget)
        all_ranked = ranker.rank(candidates, query, mode)
        total_items_count = len(all_ranked)

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
        )

        last_pack_path = self._root / ".context-router" / "last-pack.json"
        last_pack_path.write_text(pack.model_dump_json(indent=2))

        return pack

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
        runtime_signals: list[RuntimeSignal] | None = None,
        past_debug_files: set[str] | None = None,
        feedback_adjustments: dict[str, float] | None = None,
    ) -> list[ContextItem]:
        """Fetch and pre-score candidate ContextItems for *mode*.

        Args:
            mode: Task mode string.
            sym_repo: Open SymbolRepository.
            edge_repo: Open EdgeRepository.
            repo_name: Logical repository name used in DB queries.
            runtime_signals: Parsed RuntimeSignal objects (debug mode).
            past_debug_files: File paths from past signals with same error_hash.
            feedback_adjustments: Per-file confidence deltas from agent feedback.

        Returns:
            List of ContextItems with source_type and confidence set.
            Reason strings are intentionally left empty here; the ranker fills
            them in from the source_type.

        Raises:
            ValueError: If *mode* is unrecognised.
        """
        signals = runtime_signals or []
        adj = feedback_adjustments or {}
        past_files = past_debug_files or set()

        if mode == "review":
            items = self._review_candidates(sym_repo, edge_repo, repo_name)
        elif mode == "implement":
            items = self._implement_candidates(sym_repo, repo_name)
        elif mode == "debug":
            items = self._debug_candidates(sym_repo, edge_repo, repo_name, signals, past_files)
        elif mode == "handover":
            items = self._handover_candidates(sym_repo, edge_repo, repo_name)
        else:
            raise ValueError(f"Unknown mode: {mode!r}")

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

    # ------------------------------------------------------------------
    # Review mode
    # ------------------------------------------------------------------

    def _review_candidates(
        self,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str,
    ) -> list[ContextItem]:
        """Build candidates prioritised for a code-review task."""
        changed_files = self._get_changed_files()
        all_symbols = sym_repo.get_all(repo_name)

        # Pre-compute adjacency for changed files (blast radius)
        blast_radius_files: set[str] = set()
        for cf in changed_files:
            adjacent = edge_repo.get_adjacent_files(repo_name, cf)
            blast_radius_files.update(adjacent)
        blast_radius_files -= changed_files  # don't double-count

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

            confidence = _REVIEW_CONFIDENCE[source_type]
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
    ) -> list[ContextItem]:
        """Build candidates prioritised for a feature-implementation task."""
        all_symbols = sym_repo.get_all(repo_name)
        items: list[ContextItem] = []

        for sym in all_symbols:
            fp = str(sym.file)
            source_type, confidence = self._classify_for_implement(sym.name, sym.kind, fp)
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
        name: str, kind: str, file_path: str
    ) -> tuple[str, float]:
        """Classify a symbol for implement-mode scoring.

        Returns:
            Tuple of (source_type, confidence).
        """
        # Entrypoints: well-known function/method names
        if kind in ("function", "method") and _ENTRYPOINT_PATTERN.match(name):
            file_name = Path(file_path).name.lower()
            is_non_entrypoint = any(
                frag in file_name for frag in _NON_ENTRYPOINT_PATH_FRAGMENTS
            )
            if not is_non_entrypoint:
                return "entrypoint", _IMPLEMENT_CONFIDENCE["entrypoint"]

        # Contracts: files whose path contains model/schema/contract keywords
        fp_lower = file_path.lower()
        if any(fragment in fp_lower for fragment in _CONTRACT_PATH_FRAGMENTS):
            return "contract", _IMPLEMENT_CONFIDENCE["contract"]

        # Extension points: abstract base classes / protocol classes
        if kind == "class" and _EXTENSION_POINT_PATTERN.search(name):
            return "extension_point", _IMPLEMENT_CONFIDENCE["extension_point"]

        # Other classes
        if kind == "class":
            return "file", _IMPLEMENT_CONFIDENCE["file_class"]

        # Other functions/methods
        if kind in ("function", "method"):
            return "file", _IMPLEMENT_CONFIDENCE["file_function"]

        return "file", _IMPLEMENT_CONFIDENCE["file"]

    # ------------------------------------------------------------------
    # Debug mode
    # ------------------------------------------------------------------

    def _debug_candidates(
        self,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str,
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
                    confidence=_DEBUG_CONFIDENCE["runtime_signal"],
                    est_tokens=_estimate_item_tokens(title, excerpt),
                )
            )

        for sym in all_symbols:
            fp = str(sym.file)
            fname = sym.file.name

            if fp in signal_paths or fname in signal_paths:
                source_type = "runtime_signal"
                confidence = _DEBUG_CONFIDENCE["runtime_signal"]
            elif fp in past_files or fname in past_files:
                source_type = "past_debug"
                confidence = _DEBUG_CONFIDENCE.get("past_debug", 0.90)
            elif self._is_test_file(fp):
                source_type = "failing_test"
                confidence = _DEBUG_CONFIDENCE["failing_test"]
            elif fp in changed_files:
                source_type = "changed_file"
                confidence = _DEBUG_CONFIDENCE["changed_file"]
            elif fp in blast_radius_files:
                source_type = "blast_radius"
                confidence = _DEBUG_CONFIDENCE["blast_radius"]
            else:
                source_type = "file"
                confidence = _DEBUG_CONFIDENCE["file"]

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

    # ------------------------------------------------------------------
    # Handover mode
    # ------------------------------------------------------------------

    def _handover_candidates(
        self,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
        repo_name: str,
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
                confidence = _HANDOVER_CONFIDENCE["changed_file"]
            elif fp in blast_radius_files:
                source_type = "blast_radius"
                confidence = _HANDOVER_CONFIDENCE["blast_radius"]
            else:
                source_type = "file"
                confidence = _HANDOVER_CONFIDENCE["file"]

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
                        _HANDOVER_CONFIDENCE["memory"],
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
                    from memory.freshness import compute_freshness as _cf
                    from contracts.models import Observation as _Obs
                    _dummy = _Obs(summary="", timestamp=dec.created_at)
                    _dummy = _dummy.model_copy(update={"confidence_score": dec.confidence})
                    dec_fresh = min(
                        _HANDOVER_CONFIDENCE["decision"],
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
        except Exception:  # noqa: BLE001
            pass  # Memory store is optional; handover works without it

        return items
