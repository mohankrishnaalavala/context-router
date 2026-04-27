"""Context ranker: sorts and budget-enforces a list of ContextItems.

The ranker is deliberately stateless with respect to storage — it receives
pre-scored ContextItem candidates from the orchestrator and is responsible
only for:

1. Annotating each item with a human-readable *reason* derived from its
   source_type.
2. Sorting items by confidence (descending).
3. Enforcing the token budget while guaranteeing at least one item per
   distinct source_type survives.
"""

from __future__ import annotations

import math
import os
import re
import sys
import threading
from collections import Counter as _Counter
from pathlib import Path
from typing import Any, Callable

from contracts.models import ContextItem

# ``graph_index.metrics`` is imported lazily inside ``_apply_hub_bridge_boost``
# to avoid a top-level import cycle (``ranking → graph_index → core →
# ranking`` via the orchestrator). ``metrics`` itself pulls in only
# ``sqlite3`` and ``sys`` so the deferred import is cheap.

_EMBED_MODEL: object | None = None
_EMBED_LOCK = threading.Lock()

# Default model used for semantic ranking.
_EMBED_MODEL_NAME: str = "all-MiniLM-L6-v2"


class _BM25Scorer:
    """In-memory Okapi BM25 scorer built from a document corpus.

    Built once per ``rank()`` call — no state persists between calls.
    Uses k1=1.5 and b=0.75 (standard Okapi BM25 defaults).
    """

    _K1 = 1.5
    _B = 0.75

    def __init__(self, docs: list[str]) -> None:
        tokenized = [list(_tokenize(d)) for d in docs]
        self._n = len(tokenized)
        dl = [len(t) for t in tokenized]
        self._avgdl = sum(dl) / max(1, self._n)
        self._tf: list[_Counter] = [_Counter(t) for t in tokenized]
        df: dict[str, int] = {}
        for tokens in tokenized:
            for t in set(tokens):
                df[t] = df.get(t, 0) + 1
        # Robertson–Spärck Jones IDF with smoothing
        self._idf: dict[str, float] = {
            t: math.log((self._n - n_t + 0.5) / (n_t + 0.5) + 1.0)
            for t, n_t in df.items()
        }

    def scores_normalized(self, query_tokens: set[str]) -> list[float]:
        """Return per-document BM25 scores normalized to [0, 1].

        Returns a list of floats of length ``len(docs)`` where 1.0 is the
        most relevant document in the corpus.
        """
        if not query_tokens or self._n == 0:
            return [0.0] * self._n
        raw = [self._score(i, query_tokens) for i in range(self._n)]
        max_s = max(raw) if any(r > 0 for r in raw) else 1.0
        return [r / max_s for r in raw]

    def _score(self, doc_idx: int, query_tokens: set[str]) -> float:
        tf = self._tf[doc_idx]
        dl = sum(tf.values())
        total = 0.0
        for t in query_tokens:
            freq = tf.get(t, 0)
            if freq == 0:
                continue
            idf = self._idf.get(t, 0.0)
            denom = freq + self._K1 * (1 - self._B + self._B * dl / max(1, self._avgdl))
            total += idf * (freq * (self._K1 + 1)) / denom
        return total


def _dedup_stubs(
    items: list[ContextItem],
) -> tuple[list[ContextItem], int]:
    """Collapse near-duplicate symbol stubs within the same file.

    v3.2 outcome ``symbol-stub-dedup`` (P1): indexers emit one ContextItem
    per Symbol, so a file with many ``__init__`` / ``__enter__`` / tiny
    helper methods produces many items whose stub excerpts are identical
    byte-for-byte (e.g. ``def __init__(`` with no body). A reviewer can
    only read so many "same-shape" stubs before they stop being useful —
    condense them into one representative item and record the collapsed
    count.

    Dedup key: all three conditions must hold::

        1. same ``path_or_ref``  (same file)
        2. same ``title`` prefix (the leading identifier token — e.g.
           ``__init__`` is the same regardless of ``(self, x)`` suffixes)
        3. same ``excerpt``      (byte-for-byte)

    The first occurrence (highest-confidence after the caller's sort) is
    kept as the representative and its existing ``duplicates_hidden``
    counter is bumped by ``N - 1``. Later duplicates are dropped.

    Negative case: two items with the same ``title`` but DIFFERENT
    excerpts (e.g. two distinct classes both named ``Config``) are NOT
    merged — the excerpt equality check guarantees distinct content
    always survives.

    Args:
        items: Ranked ContextItems, ordered so the highest-confidence
            item of each duplicate set appears first. The function does
            not re-sort.

    Returns:
        Tuple of ``(deduped_items, hidden_count)`` where ``hidden_count``
        is the total number of items dropped (i.e. the sum of per-group
        ``N - 1`` bumps). Callers should add this to
        ``ContextPack.duplicates_hidden``.
    """
    if not items:
        return [], 0

    # Map dedup_key -> index into `out` of the representative item.
    first_idx: dict[tuple[str, str, str], int] = {}
    out: list[ContextItem] = []
    dropped = 0

    for item in items:
        title_prefix = item.title.split("(", 1)[0].strip()
        key = (
            item.path_or_ref.strip().lstrip("./").lower(),
            title_prefix,
            item.excerpt,
        )
        idx = first_idx.get(key)
        if idx is None:
            first_idx[key] = len(out)
            out.append(item)
            continue
        # Duplicate: bump the representative's duplicates_hidden counter
        # and drop this item.
        rep = out[idx]
        out[idx] = rep.model_copy(
            update={"duplicates_hidden": getattr(rep, "duplicates_hidden", 0) + 1}
        )
        dropped += 1
    return out, dropped


# Public alias for cross-package use (orchestrator, tests).
dedup_stubs = _dedup_stubs

# Matches test files and common test-directory layouts across Python, Java, TS/JS, C#.
_TEST_PATH_RE = re.compile(
    r"(^|[\\/])tests?[\\/]"
    r"|(^|[\\/])__tests__[\\/]"
    r"|(^|[\\/])spec[\\/]"
    r"|(^|[\\/])test_[^/\\]+"
    r"|(^|[\\/])[^/\\]+_test\.[a-zA-Z]"
    r"|(^|[\\/])[^/\\]+[Tt]est\.[a-zA-Z]"
    r"|(^|[\\/])[^/\\]+[Ss]pec\.[a-zA-Z]",
)

_AUX_PATH_RE = re.compile(
    r"(^|[\\/])(?:scripts?|docs_src|examples?|fixtures|stubs|mocks)[\\/]",
    re.IGNORECASE,
)


def _is_test_or_script_path(path: str) -> bool:
    """Return True when *path* looks like a test file or auxiliary script."""
    return bool(_TEST_PATH_RE.search(path) or _AUX_PATH_RE.search(path))


def _dedup_by_file(
    items: list[ContextItem],
) -> tuple[list[ContextItem], int]:
    """Keep only the highest-confidence item per unique path_or_ref.

    ``_dedup_stubs`` collapses same-title+excerpt duplicates, but multiple
    distinct symbols from the same file each survive with their own slot.
    In dense codebases this means Pet.java (×3) + Owner.java (×2) fills a
    5-item window, leaving no room for PetController.java.

    Items must already be sorted by confidence descending so the first
    occurrence of each path is the best representative.

    Returns:
        Tuple of ``(deduped_items, hidden_count)``.
    """
    if not items:
        return [], 0
    seen: dict[str, int] = {}
    out: list[ContextItem] = []
    dropped = 0
    for item in items:
        key = item.path_or_ref.strip().lstrip("./").lower()
        idx = seen.get(key)
        if idx is None:
            seen[key] = len(out)
            out.append(item)
        else:
            rep = out[idx]
            out[idx] = rep.model_copy(
                update={"duplicates_hidden": getattr(rep, "duplicates_hidden", 0) + 1}
            )
            dropped += 1
    return out, dropped


def _embed_model_is_cached(model_name: str = _EMBED_MODEL_NAME) -> bool:
    """Return True if the Hugging Face model directory for *model_name* exists.

    We detect "already downloaded" by looking for the expected model directory
    under the Hugging Face hub cache. This lets callers skip a progress bar on
    subsequent runs. The check is a conservative existence test — if the
    directory exists but is partial, ``SentenceTransformer`` will re-download
    only the missing blobs anyway.
    """
    base = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    candidates: list[Path] = []
    if base:
        candidates.append(Path(base) / "hub" / f"models--sentence-transformers--{model_name}")
        candidates.append(Path(base) / f"models--sentence-transformers--{model_name}")
    candidates.append(
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / f"models--sentence-transformers--{model_name}"
    )
    return any(p.exists() for p in candidates)


def _get_embed_model(
    progress_cb: Callable[[str], None] | None = None,
) -> object:
    """Lazy-load the sentence-transformers model; returns False if unavailable.

    Args:
        progress_cb: Optional callable invoked with status messages during
            model download (e.g. "Downloading all-MiniLM-L6-v2 (~33 MB)…").
            Called only on the first load (when the model isn't cached).
    """
    global _EMBED_MODEL
    if _EMBED_MODEL is not None:
        return _EMBED_MODEL
    with _EMBED_LOCK:
        if _EMBED_MODEL is None:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import]
            except ImportError:
                # Silent-failure rule: naming the missing dependency is
                # required so users can recover without guessing.
                sys.stderr.write(
                    "warning: --with-semantic requested but the "
                    "'sentence-transformers' package is not installed; "
                    "semantic boost disabled. Install with "
                    "`pip install sentence-transformers` to enable it.\n"
                )
                _EMBED_MODEL = False  # sentinel: embeddings unavailable
                return _EMBED_MODEL
            try:
                if progress_cb is not None and not _embed_model_is_cached():
                    try:
                        progress_cb(
                            f"Downloading {_EMBED_MODEL_NAME} (~33 MB)… this happens only once."
                        )
                    except Exception:  # noqa: BLE001
                        pass  # progress is best-effort
                _EMBED_MODEL = SentenceTransformer(_EMBED_MODEL_NAME)
                if progress_cb is not None:
                    try:
                        progress_cb("Model ready.")
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(
                    f"warning: --with-semantic could not load "
                    f"'{_EMBED_MODEL_NAME}' ({type(exc).__name__}: {exc}); "
                    f"semantic boost disabled for this run.\n"
                )
                _EMBED_MODEL = False  # sentinel: embeddings unavailable
    return _EMBED_MODEL

# Minimum characters in a query token to be used for boosting (filters stop words)
_MIN_TOKEN_LEN = 3

# Map source_type → human-readable reason string.
_REASON: dict[str, str] = {
    "changed_file": "Modified in current diff",
    "blast_radius": "Depends on or is imported by a changed file",
    "impacted_test": "Tests code affected by this change",
    "config": "Configuration file touched by change",
    "entrypoint": "Public API entry point",
    "contract": "Data contract or interface definition",
    "extension_point": "Plugin or extension point",
    "file": "Referenced in codebase",
    # Debug mode
    "runtime_signal": "Mentioned in runtime error or stack trace",
    "failing_test": "Test file likely related to the failure",
    # Handover mode
    "memory": "Recorded in session memory",
    "decision": "Architectural decision record",
    # Call flow (P5)
    "call_chain": "Reachable via function call chain from error site",
    # Transitive blast radius (P1-5)
    "blast_radius_transitive": "Transitively reachable via call chain from a changed file",
}

_DEFAULT_REASON = "Included in context pack"

# Adaptive top-k constants (v4.2 T3; plateau rule added v4.3 C2)
_ADAPTIVE_TOPK_FLOOR_RATIO: float = 0.6
_ADAPTIVE_TOPK_PLATEAU_DELTA: float = 0.02   # max step between consecutive plateau items
_ADAPTIVE_TOPK_ABS_FLOOR: float = 0.40       # plateau items must be below this threshold
_ADAPTIVE_TOPK_MODES: frozenset[str] = frozenset({"review", "implement"})

# v4.4 C1: source-file basename boost — lifts exact module name matches above
# test files that merely mention the module in their excerpts.
_SOURCE_FILE_BOOST: float = 1.3


def _tokenize(text: str) -> set[str]:
    """Return lowercase tokens from *text* that are at least _MIN_TOKEN_LEN chars.

    CamelCase/PascalCase identifiers are split before lowercasing so that
    ``OAuth2PasswordBearer`` contributes ``oauth2``, ``password``, ``bearer``
    to the BM25 corpus — matching queries that use those individual terms.
    """
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    return {t for t in re.split(r"[^a-z0-9]+", expanded.lower()) if len(t) >= _MIN_TOKEN_LEN}


def _discover_db_path(items: list[ContextItem]) -> Path | None:
    """Walk up from each item's path_or_ref to find ``.context-router/context-router.db``.

    The orchestrator owns the SQLite connection but does not pass it to
    the ranker (deliberate — keeps the ranker stateless). To read the
    persistent embeddings table we re-open a read-only connection by
    discovering the project root from the first item with a filesystem
    path that resolves to an existing ``.context-router/`` dir.

    Returns:
        Resolved path to ``context-router.db`` or ``None`` if discovery
        fails (e.g. items reference UUIDs / commit SHAs only, or no
        ``.context-router/`` dir exists above any candidate path).
    """
    seen_starts: set[Path] = set()
    for item in items:
        ref = item.path_or_ref
        if not ref:
            continue
        try:
            candidate = Path(ref)
        except Exception:  # noqa: BLE001
            continue
        # Skip non-filesystem refs like UUIDs / commit SHAs.
        if not candidate.is_absolute() and "/" not in ref and "\\" not in ref:
            continue
        try:
            start = candidate.resolve().parent if candidate.suffix else candidate.resolve()
        except Exception:  # noqa: BLE001
            continue
        if start in seen_starts:
            continue
        seen_starts.add(start)
        current = start
        # Cap the walk to avoid touching the whole filesystem on bad input.
        for _ in range(30):
            db = current / ".context-router" / "context-router.db"
            if db.is_file():
                return db
            if current.parent == current:
                break
            current = current.parent
    return None


class ContextRanker:
    """Sorts and trims ContextItems to fit within a token budget.

    Implements the ``Ranker`` protocol defined in ``contracts.interfaces``.

    Args:
        token_budget: Maximum total estimated tokens for the output pack.
            Pass 0 to disable budget enforcement (return all items sorted).
    """

    def __init__(
        self,
        token_budget: int = 8_000,
        use_embeddings: bool = True,
        progress_cb: Callable[[str], None] | None = None,
        use_hub_boost: bool | None = None,
        db_connection: Any | None = None,
        memory_budget_pct: float = 0.15,
    ) -> None:
        """Initialise the ranker with a token budget.

        Args:
            token_budget: Hard upper limit on total ``est_tokens`` in the
                returned item list.  0 means unlimited.
            use_embeddings: If True, apply semantic similarity boosting via
                sentence-transformers (requires ``pip install sentence-transformers``).
                Defaults to True; when the model is unavailable a stderr warning is
                emitted and ranking proceeds without semantic boosting.
            progress_cb: Optional callback invoked with status messages during
                first-time model download (see :func:`_get_embed_model`).
                Used by the CLI to render a rich progress bar; must be None
                on MCP stdio transport to avoid corrupting JSON-RPC frames.
            use_hub_boost: If True, apply the Phase-3 hub / bridge structural
                boost after BM25 and before semantic ranking. If ``None``
                (the default), the flag is resolved per-call from the
                ``CAPABILITIES_HUB_BOOST`` environment variable or from the
                discovered project's ``capabilities.hub_boost`` config key
                (the Orchestrator does not pass this flag today, hence the
                env-/config-driven fallback).
            db_connection: Optional pre-opened SQLite connection to reuse
                for structural lookups (hub/bridge boost + symbol id
                resolution). When supplied, the ranker does NOT open a new
                ``sqlite3.Connection`` per ``rank()`` call — this avoids
                connection-lifetime churn on large repos when the Orchestrator
                already holds an open ``Database`` instance. When ``None``
                (ranker used standalone, e.g. unit tests), the boost falls
                back to opening a fresh connection from the discovered
                db_path. Callers retain ownership — the ranker never closes
                a connection it did not open.
        """
        self._budget = token_budget
        self._use_embeddings = use_embeddings
        self._progress_cb = progress_cb
        self._use_hub_boost = use_hub_boost
        self._db_connection = db_connection
        self._memory_budget_pct = memory_budget_pct
        # P1-6: BM25 corpus cache — maps items_key -> _BM25Scorer
        # Bounded at 5 entries to avoid unbounded memory growth.
        self._bm25_cache: dict[int, Any] = {}
        # v3 phase-2: latch so `embeddings missing for N of M` warns at most
        # once per rank() call (reset at the start of each semantic boost).
        self._missing_warn_emitted: bool = False

    def rank(
        self,
        items: list[ContextItem],
        query: str,
        mode: str,
        *,
        diff_spec: str | None = None,
        project_root: Path | None = None,
        boosted_items_sink: list[str] | None = None,
        source_discovery: bool = False,
    ) -> list[ContextItem]:
        """Rank *items* and enforce the token budget.

        Steps:
        1. Annotate each item's ``reason`` from its ``source_type``.
        2. Apply query-relevance confidence boost (keyword overlap + BM25).
        3. If ``use_embeddings=True``, apply semantic similarity boost in
           every mode (a model must be available; otherwise the call is a
           no-op at the boost helper level).
        4. v3.2 ``diff-aware-ranking-boost`` (P2): when *diff_spec* is
           supplied, bump confidence by ``+0.15`` on any item whose
           underlying symbol's ``[line_start, line_end]`` overlaps the
           changed-line set for its file.
        5. Sort by ``confidence`` descending.
        6. Trim to token budget while keeping at least one item per
           ``source_type`` (so every category of evidence is represented).

        Args:
            items: Pre-scored ContextItem candidates.
            query: Free-text task description used for relevance boosting.
            mode: Task mode — currently informational. The semantic boost is
                applied in every mode when ``use_embeddings=True``.
            diff_spec: Optional diff spec passed through to the v3.2
                ``diff-aware-ranking-boost`` helper. ``"HEAD"`` means
                staged + unstaged vs. ``HEAD``; any other value is treated
                as a commit SHA to diff against its parent. When ``None``
                the boost is a strict no-op (the contractual negative case
                in the DoD).
            project_root: Repository root for the ``git diff`` subprocess.
                Required when *diff_spec* is set; ignored otherwise. When
                missing despite *diff_spec* being set, the boost emits a
                single stderr warning and proceeds without boosting.
            boosted_items_sink: Optional list the ranker appends the ``id``
                of every diff-boosted item to. The Orchestrator supplies
                this to surface telemetry under
                ``ContextPack.metadata["boosted_items"]``.
            source_discovery: True when the caller is trying to discover
                source files for a free-text task rather than diagnose a
                concrete failing test/runtime signal. In this mode test and
                auxiliary paths are downweighted unless they carry primary
                debug evidence.

        Returns:
            Ranked and budget-enforced list of ContextItems.
        """
        if not items:
            return []

        query_tokens = _tokenize(query)
        annotated = [self._annotate(item) for item in items]
        boosted = self._apply_bm25_boost(
            annotated,
            query_tokens,
            mode=mode,
            source_discovery=source_discovery,
        )
        boosted = self._apply_source_file_boost(boosted, query_tokens)  # v4.4 C1
        # v3 phase-3 (outcome: hub-bridge-ranking-signals): structural
        # boost applied AFTER BM25 so BM25's normalised signal is not
        # flattened, and BEFORE the semantic pass so both additive
        # signals compose on the same base. Off by default — resolved
        # per-call from ``CAPABILITIES_HUB_BOOST`` env var or from
        # ``capabilities.hub_boost`` in the discovered project config.
        if self._resolve_hub_boost_enabled(items):
            boosted = self._apply_hub_bridge_boost(boosted)
        # v3 phase-2 (outcome: semantic-default-with-progress): the semantic
        # boost now applies in every pack mode when ``use_embeddings=True``.
        # Prior to phase 2 this was gated to ``mode == "implement"`` and a
        # phase-1 stderr warning fired outside implement mode. That warning
        # is now obsolete because there is no longer a silent no-op: the
        # flag takes effect everywhere. ``mode`` is still threaded through
        # for future per-mode tuning but no longer gates the call.
        if self._use_embeddings:
            boosted = self._apply_semantic_boost(boosted, query)
        # v3.2 outcome ``diff-aware-ranking-boost`` (P2): run AFTER BM25 +
        # hub/bridge + semantic so the +0.15 structural nudge composes on
        # top of the content-based signals, and BEFORE the final sort so
        # boosted items can actually change the order. Strict no-op when
        # ``diff_spec`` is None (the DoD's negative case).
        if diff_spec:
            boosted = self._apply_diff_aware_boost(
                boosted,
                diff_spec=diff_spec,
                project_root=project_root,
                boosted_items_sink=boosted_items_sink,
            )
        sorted_items = sorted(boosted, key=lambda i: i.confidence, reverse=True)

        # v3.2 outcome ``symbol-stub-dedup`` (P1): collapse identical
        # symbol stubs within the same file BEFORE budget enforcement so
        # the budget fills with distinct content. Runs unconditionally —
        # the helper is a no-op when no near-duplicates exist.
        sorted_items, _ = _dedup_stubs(sorted_items)

        # v4.1 fix: after stub-dedup, enforce one item per unique file path.
        # Multiple symbols from the same file (different excerpts) each
        # survive stub-dedup and waste top-k slots — Pet.java ×3 consumed
        # 3/5 slots in the v4.0 benchmark, missing PetController.java.
        sorted_items, _ = _dedup_by_file(sorted_items)

        authoritative_changed_files = False
        if source_discovery:
            changed_file_items = [
                item for item in sorted_items if item.source_type == "changed_file"
            ]
            if changed_file_items:
                sorted_items = changed_file_items
                authoritative_changed_files = True

        if authoritative_changed_files:
            adaptive_mode = "debug"
        elif source_discovery:
            adaptive_mode = "implement"
        else:
            adaptive_mode = mode

        pinned_source: ContextItem | None = None
        if source_discovery:
            pinned_source = next(
                (
                    item
                    for item in sorted_items
                    if item.source_type
                    not in {"memory", "decision", "runtime_signal", "failing_test"}
                    and not _is_test_or_script_path(item.path_or_ref or "")
                ),
                None,
            )

        if self._budget <= 0:
            return self._apply_adaptive_top_k(sorted_items, adaptive_mode)

        # Sub-budget: memory/decision items capped at memory_budget_pct of total budget
        _mem_types = frozenset({"memory", "decision"})
        memory_items = [i for i in sorted_items if i.source_type in _mem_types]
        code_items = [i for i in sorted_items if i.source_type not in _mem_types]

        memory_cap = int(self._budget * self._memory_budget_pct)
        trimmed_memory = self._enforce_budget(memory_items, cap=memory_cap)
        remaining = self._budget - sum(i.est_tokens for i in trimmed_memory)
        trimmed_code = self._enforce_budget(
            sorted(code_items, key=lambda i: i.confidence, reverse=True),
            cap=max(0, remaining),
        )

        result = sorted(trimmed_memory + trimmed_code, key=lambda i: i.confidence, reverse=True)
        if pinned_source is not None and all(
            item.path_or_ref != pinned_source.path_or_ref for item in result
        ):
            result = [pinned_source] + result
            total = 0
            trimmed: list[ContextItem] = []
            for item in result:
                if total + item.est_tokens <= self._budget or (
                    item.path_or_ref == pinned_source.path_or_ref
                ):
                    trimmed.append(item)
                    total += item.est_tokens
            result = sorted(trimmed, key=lambda i: i.confidence, reverse=True)
        return self._apply_adaptive_top_k(result, adaptive_mode)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_adaptive_top_k(
        self, items: list[ContextItem], mode: str
    ) -> list[ContextItem]:
        """Drop low-signal trailing items in review/implement modes.

        Two rules run independently; the more aggressive cut wins:

        Rule 1 (floor ratio): drop trailing items below
          FLOOR_RATIO × leader_confidence. Catches outlier stragglers
          when the leader has a clearly dominant score.

        Rule 2 (plateau): when leader.confidence > ABS_FLOOR, drop from the
          first index i where items[i].confidence < ABS_FLOOR AND
          items[i-1].confidence - items[i].confidence < PLATEAU_DELTA.
          Catches flat tails that cluster just below ABS_FLOOR.
          Guard prevents misfiring when all items have near-zero confidence
          (empty query / no BM25 signal).

        A no-op in debug/handover modes and when fewer than 2 items present.
        """
        if len(items) < 2 or mode not in _ADAPTIVE_TOPK_MODES:
            return items

        # Rule 1: floor ratio
        floor = _ADAPTIVE_TOPK_FLOOR_RATIO * items[0].confidence
        last_keep = len(items) - 1
        while last_keep > 0 and items[last_keep].confidence < floor:
            last_keep -= 1

        # Rule 2: plateau cut — only when the leader has meaningful confidence.
        # Guard prevents firing when all items are near-zero (no BM25 signal).
        if items[0].confidence > _ADAPTIVE_TOPK_ABS_FLOOR:
            for i in range(1, len(items)):
                if (
                    items[i].confidence < _ADAPTIVE_TOPK_ABS_FLOOR
                    and items[i - 1].confidence - items[i].confidence < _ADAPTIVE_TOPK_PLATEAU_DELTA
                ):
                    last_keep = min(last_keep, i - 1)
                    break

        return items[: last_keep + 1]

    def _apply_semantic_boost(self, items: list[ContextItem], query: str) -> list[ContextItem]:
        """Boost items using cosine similarity from sentence-transformers.

        Runs whenever ``use_embeddings=True`` and a model is available — in
        every pack mode (review, debug, implement, handover). Formula:
        ``boost = min(0.15, max(0, sim - 0.3) * 0.3)``. Items with
        similarity <= 0.3 receive no boost.

        v3 phase-2 (outcome ``proactive-embedding-cache``): item vectors
        are preferentially loaded from the persistent ``embeddings`` table
        populated by ``context-router embed``. Items without a stored
        vector fall back to on-the-fly encoding AND a single stderr
        warning is emitted (per CLAUDE.md silent-failure rule).
        """
        if not query or not items:
            return items
        model = _get_embed_model(progress_cb=self._progress_cb)
        if not model:
            sys.stderr.write(
                "warning: use_embeddings=True but semantic model is unavailable; "
                "semantic re-ranking skipped for this call.\n"
            )
            return items
        # Reset the per-call "missing embeddings" warning latch so each
        # rank() call is permitted at most one stderr line.
        self._missing_warn_emitted = False
        try:
            import numpy as np  # type: ignore[import]

            # 1. Encode the query once. Query text is user input — never
            #    cached. (Only the codebase symbols are pre-embedded.)
            query_emb = model.encode([query], normalize_embeddings=True)

            # 2. Bulk-fetch any pre-computed item vectors from the
            #    persistent embeddings table.
            stored = self._fetch_stored_vectors(items)

            # 3. Encode only the items that aren't in the table.
            missing_idxs = [
                idx for idx, it in enumerate(items) if id(it) not in stored
            ]
            if missing_idxs:
                missing_texts = [
                    f"{items[idx].title} {items[idx].excerpt}"
                    for idx in missing_idxs
                ]
                fallback_embs = model.encode(
                    missing_texts, normalize_embeddings=True, batch_size=32
                )
                # Outcome contract: silent fallback is a bug. Warn once.
                self._warn_missing_embeddings(len(missing_idxs), len(items))
            else:
                fallback_embs = np.zeros((0, query_emb.shape[1]), dtype=np.float32)

            # 4. Assemble the per-item embedding matrix in original order.
            item_embs = np.zeros((len(items), query_emb.shape[1]), dtype=np.float32)
            fallback_pos = 0
            for idx, it in enumerate(items):
                vec = stored.get(id(it))
                if vec is None:
                    item_embs[idx] = fallback_embs[fallback_pos]
                    fallback_pos += 1
                else:
                    item_embs[idx] = vec

            similarities = (item_embs @ query_emb.T).flatten()
            result = []
            for item, sim in zip(items, similarities):
                sim_f = float(sim)
                boost = min(0.15, max(0.0, sim_f - 0.3) * 0.3)
                if boost > 0:
                    new_conf = min(0.95, item.confidence + boost)
                    result.append(item.model_copy(update={"confidence": new_conf}))
                else:
                    result.append(item)
            return result
        except Exception:
            return items

    # ------------------------------------------------------------------
    # Persistent embedding lookup (proactive cache)
    # ------------------------------------------------------------------

    def _fetch_stored_vectors(
        self, items: list[ContextItem]
    ) -> dict[int, Any]:
        """Return ``{id(item): np.ndarray}`` for items with stored vectors.

        Implementation notes:
            * Discovers the SQLite database by walking up from the first
              item with a filesystem-looking ``path_or_ref`` until a
              ``.context-router/context-router.db`` file appears.
            * Resolves ``(file_path, name) → symbol_id`` in one query
              per repo, then bulk-fetches vectors keyed by symbol_id.
            * Returns ``{}`` on any failure — semantic ranking degrades
              gracefully via the on-the-fly fallback path.
        """
        try:
            import numpy as np  # type: ignore[import]
        except Exception:  # noqa: BLE001
            return {}

        db_path = _discover_db_path(items)
        if db_path is None:
            return {}

        try:
            import sqlite3

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                # Group items by repo so we issue one bulk lookup per repo
                # (typical pack has only one repo, so this is one query).
                by_repo: dict[str, list[ContextItem]] = {}
                for it in items:
                    by_repo.setdefault(it.repo or "default", []).append(it)

                results: dict[int, Any] = {}
                for repo_name, group in by_repo.items():
                    # Build (path, name) → item lookup. The ranker doesn't
                    # know symbol_ids; we resolve them via the symbols table.
                    keys: list[tuple[str, str]] = []
                    item_by_key: dict[tuple[str, str], list[ContextItem]] = {}
                    for it in group:
                        # title is "name (filename)"; pull the leading name.
                        name = it.title.split(" (")[0].strip()
                        if not name:
                            continue
                        key = (it.path_or_ref, name)
                        keys.append(key)
                        item_by_key.setdefault(key, []).append(it)

                    if not keys:
                        continue

                    # Resolve (file_path, name) → symbol_id in one query.
                    placeholders = ",".join("(?, ?)" for _ in keys)
                    flat: list[str] = []
                    for fp, nm in keys:
                        flat.append(fp)
                        flat.append(nm)
                    rows = conn.execute(
                        f"""
                        WITH wanted(file_path, name) AS (VALUES {placeholders})
                        SELECT s.id, s.file_path, s.name
                        FROM symbols s
                        JOIN wanted w
                          ON s.file_path = w.file_path AND s.name = w.name
                        WHERE s.repo = ?
                        """,
                        (*flat, repo_name),
                    ).fetchall()

                    sid_by_key: dict[tuple[str, str], int] = {}
                    for r in rows:
                        sid_by_key[(r["file_path"], r["name"])] = int(r["id"])
                    if not sid_by_key:
                        continue

                    # Bulk-fetch vectors for the resolved symbol_ids.
                    sids = list(sid_by_key.values())
                    chunk = 500
                    vec_by_sid: dict[int, bytes] = {}
                    for start in range(0, len(sids), chunk):
                        ids_chunk = sids[start : start + chunk]
                        ph = ",".join("?" * len(ids_chunk))
                        vrows = conn.execute(
                            f"""
                            SELECT symbol_id, vector
                            FROM embeddings
                            WHERE repo = ? AND model = ?
                              AND symbol_id IN ({ph})
                            """,
                            (repo_name, _EMBED_MODEL_NAME, *ids_chunk),
                        ).fetchall()
                        for vr in vrows:
                            vec_by_sid[int(vr["symbol_id"])] = bytes(vr["vector"])

                    for key, sid in sid_by_key.items():
                        blob = vec_by_sid.get(sid)
                        if blob is None:
                            continue
                        arr = np.frombuffer(blob, dtype=np.float32)
                        for it in item_by_key.get(key, []):
                            results[id(it)] = arr
                return results
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            # Any DB-side failure → empty mapping; on-the-fly fallback runs.
            return {}

    def _warn_missing_embeddings(self, missing: int, total: int) -> None:
        """Emit a one-time stderr warning when items lack stored vectors.

        Per CLAUDE.md's silent-failure rule, the on-the-fly fallback must
        not be silent. We emit at most one warning per ``rank()`` call.
        """
        if self._missing_warn_emitted:
            return
        self._missing_warn_emitted = True
        try:
            print(
                f"context-router: embeddings missing for {missing} of {total} "
                "items — run `context-router embed` to eliminate this cost.",
                file=sys.stderr,
            )
        except Exception:  # noqa: BLE001
            # Stderr write failure should never break ranking.
            pass

    def _apply_bm25_boost(
        self,
        items: list[ContextItem],
        query_tokens: set[str],
        mode: str = "",
        source_discovery: bool = False,
    ) -> list[ContextItem]:
        """Re-score items using BM25 relevance combined with structural confidence.

        Formula: ``final_conf = min(0.95, 0.6 × structural_conf + 0.4 × bm25_score)``

        *bm25_score* is normalized to [0, 1] across all candidates so the most
        BM25-relevant item gets the full 0.40 bonus.  Items with no query
        match get a score of 0, so their final confidence is 60% of their
        structural score — they remain in the pack but yield priority to
        query-relevant symbols.

        v4.1: corpus now includes the file basename so that queries naming a
        specific file (e.g. "Fix OAuth2 form docstrings") give a stronger
        signal to ``oauth2.py`` over ``test_security_oauth2_optional.py``.
        Full path_or_ref is still excluded — repository names with query
        terms would cause false positives.

        v4.1: a 0.85× multiplier is applied to test files and auxiliary
        scripts in non-debug modes, preventing test functions that echo
        query terms from outranking the source file they test.
        """
        if not query_tokens or not items:
            return items
        corpus = [
            f"{Path(i.path_or_ref).name} {i.title} {i.excerpt}"
            if i.path_or_ref else f"{i.title} {i.excerpt}"
            for i in items
        ]
        # P1-6: cache BM25 corpus per unique items set to avoid rebuilding on every call
        items_key = hash(tuple(i.path_or_ref + i.title for i in items))
        if items_key not in self._bm25_cache:
            self._bm25_cache[items_key] = _BM25Scorer(corpus)
            # Keep cache bounded: evict oldest entry if > 5 entries
            if len(self._bm25_cache) > 5:
                oldest = next(iter(self._bm25_cache))
                del self._bm25_cache[oldest]
        scorer = self._bm25_cache[items_key]
        bm25_scores = scorer.scores_normalized(query_tokens)

        # Pass 1: compute pre-penalty scores and max non-test score.
        # This lets us detect whether a test file is the *sole* high-signal
        # item (e.g. bulletproof-react T3: GT is src/test/server/handlers/…).
        # When no non-test item scores as high, the penalty is skipped so the
        # correct file is not suppressed.
        pre_scores = [
            min(0.95, 0.6 * item.confidence + 0.4 * bm25)
            for item, bm25 in zip(items, bm25_scores)
        ]
        max_non_test_conf = max(
            (s for item, s in zip(items, pre_scores)
             if not _is_test_or_script_path(item.path_or_ref or "")),
            default=0.0,
        )

        # Pass 2: build result, applying an auxiliary-path penalty when a
        # non-auxiliary competitor has comparable signal. Runtime/failing-test
        # evidence is primary debug signal and is never penalized. Plain debug
        # mode keeps tests eligible unless the caller has explicitly marked the
        # task as source discovery.
        result = []
        for item, pre_score in zip(items, pre_scores):
            new_conf = pre_score
            should_penalize_aux = (
                _is_test_or_script_path(item.path_or_ref or "")
                and (mode != "debug" or source_discovery)
                and item.source_type not in {"runtime_signal", "failing_test"}
            )
            if should_penalize_aux and max_non_test_conf >= new_conf * 0.70:
                new_conf = new_conf * 0.65
            result.append(item.model_copy(update={"confidence": new_conf}))
        return result

    # ------------------------------------------------------------------
    # Source-file basename boost (v4.4 C1: source-file-boost)
    # ------------------------------------------------------------------

    def _apply_source_file_boost(
        self,
        items: list[ContextItem],
        query_tokens: set[str],
    ) -> list[ContextItem]:
        """Boost items whose file basename stem exactly matches a query token.

        If the query contains "oauth2" and the item's file is "oauth2.py"
        (stem = "oauth2"), apply a 1.3x multiplier capped at 0.95.
        Only fires for non-test, non-script paths. This targets the known
        BM25 failure mode where test files that mention a module name in
        excerpts outrank the source module itself.
        """
        if not query_tokens:
            return items
        result = []
        for item in items:
            path = item.path_or_ref or ""
            stem = Path(path).stem.lower().replace("-", "_").replace(".", "_")
            if (
                stem in query_tokens
                and not _is_test_or_script_path(path)
            ):
                boosted = min(0.95, item.confidence * _SOURCE_FILE_BOOST)
                result.append(item.model_copy(update={"confidence": boosted}))
            else:
                result.append(item)
        return result

    # ------------------------------------------------------------------
    # Hub / bridge structural boost (v3 phase-3: hub-bridge-ranking-signals)
    # ------------------------------------------------------------------

    def _resolve_hub_boost_enabled(self, items: list[ContextItem]) -> bool:
        """Return True iff the hub/bridge boost should run for this call.

        Resolution order:
            1. The constructor-supplied ``use_hub_boost`` overrides if set.
            2. ``CAPABILITIES_HUB_BOOST`` env var (``1``/``true``/``yes``
               → True; anything else False). Makes the flag toggleable
               from shell scripts / smoke tests without editing config.
            3. ``capabilities.hub_boost`` in the discovered project
               ``.context-router/config.yaml``. ``False`` by default.

        Silent no-ops are a policy violation (see CLAUDE.md). If the
        boost is requested but structurally cannot run (no db found, no
        edges indexed), ``_apply_hub_bridge_boost`` warns to stderr.
        """
        if self._use_hub_boost is not None:
            return bool(self._use_hub_boost)

        env = os.environ.get("CAPABILITIES_HUB_BOOST")
        if env is not None:
            return env.strip().lower() in {"1", "true", "yes", "on"}

        db_path = _discover_db_path(items)
        if db_path is None:
            return False
        try:
            from contracts.config import load_config  # local to avoid import cost

            cfg = load_config(db_path.parent.parent)
            return bool(getattr(cfg.capabilities, "hub_boost", False))
        except Exception:  # noqa: BLE001
            return False

    def _apply_hub_bridge_boost(
        self, items: list[ContextItem]
    ) -> list[ContextItem]:
        """Lift items whose underlying symbol is a hub or bridge.

        Formula (caps at ``+0.10``):

            boost = min(0.10, 0.07 * hub_score + 0.05 * bridge_score)

        Resolution steps:
            1. Discover the project DB from the item paths (reuses
               :func:`_discover_db_path`, so read-only items like
               memory / decisions are ignored for this pass).
            2. Resolve ``(path_or_ref, name) → symbol_id`` via one bulk
               query per repo, mirroring :meth:`_fetch_stored_vectors`.
            3. Fetch hub + bridge scores and apply the capped boost.

        Silent-failure rule: if the DB cannot be found OR structural
        metrics are empty (e.g. graph not yet built), we emit a single
        stderr line and return the original list. Items whose
        ``symbol_id`` cannot be resolved (e.g. FTS-only hits with no
        matching symbol row) are passed through untouched.
        """
        if not items:
            return items

        db_path = _discover_db_path(items)
        if db_path is None:
            self._warn_hub_boost_skipped("no .context-router DB discovered")
            return items

        sid_by_item_id = self._resolve_symbol_ids(items, db_path)
        if not sid_by_item_id:
            # No items map to a known symbol — safe to skip silently
            # (this path is hit for memory-/decision-only packs).
            return items

        try:
            # Deferred import — see module-level comment for why.
            from graph_index.metrics import (  # noqa: PLC0415
                compute_bridge_scores,
                compute_hub_scores,
            )

            # Prefer the Orchestrator-supplied connection. Opening a fresh
            # one per pack on large repos is wasted I/O (per v3.1
            # hub-bridge-sqlite-reuse P2). Fall back to a fresh connection
            # only when the ranker is used standalone (no db_connection).
            if self._db_connection is not None:
                conn = self._db_connection
                owns_conn = False
            else:
                import sqlite3  # noqa: PLC0415

                conn = sqlite3.connect(db_path)
                owns_conn = True
            try:
                # Use first resolved repo scope. Packs are single-repo in
                # practice; if multi-repo ever arrives, a caller-side
                # loop over repos would be the right extension.
                repo_name = self._dominant_repo(items)
                hub = compute_hub_scores(conn, repo_name)
                bridge = compute_bridge_scores(conn, repo_name)
            finally:
                if owns_conn:
                    conn.close()
        except Exception as exc:  # noqa: BLE001
            self._warn_hub_boost_skipped(
                f"metrics query failed ({type(exc).__name__}: {exc})"
            )
            return items

        if not hub and not bridge:
            self._warn_hub_boost_skipped(
                "hub / bridge metrics empty — is the graph indexed?"
            )
            return items

        out: list[ContextItem] = []
        for item in items:
            sid = sid_by_item_id.get(id(item))
            # Public attribute fallback so callers that carry a
            # ``symbol_id`` on a custom subclass still benefit.
            if sid is None:
                sid = getattr(item, "symbol_id", None)
            if sid is None:
                out.append(item)
                continue
            h = hub.get(int(sid), 0.0)
            b = bridge.get(int(sid), 0.0)
            raw = 0.07 * h + 0.05 * b
            boost = min(0.10, raw)
            if boost <= 0:
                out.append(item)
                continue
            new_conf = min(0.95, item.confidence + boost)
            out.append(item.model_copy(update={"confidence": new_conf}))
        return out

    def _resolve_symbol_ids(
        self, items: list[ContextItem], db_path: Path
    ) -> dict[int, int]:
        """Return ``{id(item): symbol_id}`` for items resolvable via symbols.

        Mirrors :meth:`_fetch_stored_vectors` — same (file_path, name)
        lookup keyed through a WITH-VALUES CTE. Returns ``{}`` on any
        failure so the hub/bridge path degrades gracefully.

        Reuses ``self._db_connection`` when the Orchestrator supplied one
        (v3.1 hub-bridge-sqlite-reuse). Only opens a fresh connection when
        the ranker is used standalone.
        """
        try:
            import sqlite3  # noqa: PLC0415

            if self._db_connection is not None:
                conn = self._db_connection
                owns_conn = False
                # Row factory is set by Database.connect() already, but be
                # defensive: our WITH-VALUES CTE expects column access by
                # name, and an orchestrator-shared connection must keep
                # that invariant for the duration of this call.
                prev_factory = conn.row_factory
                conn.row_factory = sqlite3.Row
            else:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                owns_conn = True
                prev_factory = None
            try:
                by_repo: dict[str, list[ContextItem]] = {}
                for it in items:
                    by_repo.setdefault(it.repo or "default", []).append(it)

                result: dict[int, int] = {}
                for repo_name, group in by_repo.items():
                    keys: list[tuple[str, str]] = []
                    item_by_key: dict[tuple[str, str], list[ContextItem]] = {}
                    for it in group:
                        name = it.title.split(" (")[0].strip()
                        if not name or not it.path_or_ref:
                            continue
                        key = (it.path_or_ref, name)
                        keys.append(key)
                        item_by_key.setdefault(key, []).append(it)

                    if not keys:
                        continue

                    placeholders = ",".join("(?, ?)" for _ in keys)
                    flat: list[str] = []
                    for fp, nm in keys:
                        flat.append(fp)
                        flat.append(nm)
                    rows = conn.execute(
                        f"""
                        WITH wanted(file_path, name) AS (VALUES {placeholders})
                        SELECT s.id, s.file_path, s.name
                        FROM symbols s
                        JOIN wanted w
                          ON s.file_path = w.file_path AND s.name = w.name
                        WHERE s.repo = ?
                        """,
                        (*flat, repo_name),
                    ).fetchall()

                    sid_by_key: dict[tuple[str, str], int] = {}
                    for r in rows:
                        sid_by_key[(r["file_path"], r["name"])] = int(r["id"])

                    for key, sid in sid_by_key.items():
                        for it in item_by_key.get(key, []):
                            result[id(it)] = sid
                return result
            finally:
                if owns_conn:
                    conn.close()
                elif prev_factory is not None:
                    # Restore the caller's row_factory so we don't leak a
                    # ranker-local invariant onto the shared connection.
                    conn.row_factory = prev_factory
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _dominant_repo(items: list[ContextItem]) -> str:
        """Return the most common non-empty ``repo`` across *items*.

        Packs are single-repo today; this helper exists so that a future
        multi-repo caller gets a deterministic pick (majority wins,
        ties go to first-seen).
        """
        counts: dict[str, int] = {}
        order: list[str] = []
        for it in items:
            key = it.repo or "default"
            if key not in counts:
                order.append(key)
            counts[key] = counts.get(key, 0) + 1
        if not order:
            return "default"
        order.sort(key=lambda k: counts[k], reverse=True)
        return order[0]

    def _warn_hub_boost_skipped(self, reason: str) -> None:
        """Emit a one-line stderr warning when the boost is requested but skipped."""
        try:
            print(
                f"context-router: hub_boost requested but skipped — {reason}",
                file=sys.stderr,
            )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Diff-aware structural boost (v3.2: diff-aware-ranking-boost)
    # ------------------------------------------------------------------

    def _apply_diff_aware_boost(
        self,
        items: list[ContextItem],
        *,
        diff_spec: str,
        project_root: Path | None,
        boosted_items_sink: list[str] | None,
    ) -> list[ContextItem]:
        """Bump items whose symbol overlaps changed lines in *diff_spec*.

        Formula: ``new_conf = min(0.95, conf + 0.15)`` for any item whose
        underlying symbol's ``[line_start, line_end]`` intersects the set
        of changed lines for its file. Items whose path isn't in the diff,
        or whose symbol can't be resolved, are passed through unchanged.

        Silent-failure rule: if ``git diff`` fails (not a repo, invalid
        SHA, missing git), emit a single stderr warning
        ``"diff-aware boost skipped: <reason>"`` and return the items
        unchanged — never silent.

        Args:
            items: Candidates AFTER BM25/hub/semantic boosts.
            diff_spec: ``"HEAD"`` or a commit SHA.
            project_root: Repo root for ``git diff``. Required.
            boosted_items_sink: Optional list receiving the ``id`` of each
                item that received the +0.15 boost (telemetry).

        Returns:
            The list with bumped-confidence copies for overlap hits.
        """
        if not items:
            return items
        if project_root is None:
            self._warn_diff_aware_skipped("no project_root supplied")
            return items

        # Deferred import — ranking should not import graph_index at module
        # load time (avoids a cycle when graph_index imports ranking via
        # the orchestrator in future refactors).
        try:
            from graph_index.blame import (  # noqa: PLC0415
                get_changed_lines,
                symbol_overlaps_diff,
            )
        except ImportError as exc:
            self._warn_diff_aware_skipped(f"graph_index.blame unavailable: {exc}")
            return items

        try:
            changed_by_path = get_changed_lines(Path(project_root), diff_spec)
        except Exception as exc:  # noqa: BLE001 — boost is best-effort
            self._warn_diff_aware_skipped(
                f"git diff failed ({type(exc).__name__}: {exc})"
            )
            return items

        if not changed_by_path:
            # Either the diff is empty OR git refused to emit one. The
            # blame module swallows failures silently, so an empty dict
            # here can mean "no changes" or "not a git repo / invalid
            # SHA". Surface the latter conservatively: warn only when
            # *project_root* isn't inside a repo (cheap to detect via
            # ``git rev-parse``); otherwise treat as "no changes" and
            # skip the boost silently — empty diff is NOT a failure.
            if not self._is_git_repo(Path(project_root)):
                self._warn_diff_aware_skipped(
                    f"not a git repository: {project_root}"
                )
            return items

        # Prefer the project_root's DB when present so tests and CLI
        # invocations resolving relative item paths don't accidentally
        # pick up the AGENT's repo DB via ``Path.resolve()`` upward-walk.
        proj_db = Path(project_root) / ".context-router" / "context-router.db"
        if proj_db.is_file():
            db_path: Path | None = proj_db
        else:
            db_path = _discover_db_path(items)
        sym_lines_by_item = self._resolve_symbol_line_ranges(items, db_path)

        # Build a per-path changed-line lookup that tolerates absolute /
        # relative / leading-"./" forms. Symbol records store repo-relative
        # paths; the diff emits repo-relative posix paths; items may carry
        # either form. Normalise on the lookup side.
        try:
            root_abs = Path(project_root).resolve()
        except (OSError, RuntimeError):
            root_abs = Path(project_root)

        norm_changed: dict[str, set[int]] = {}
        for rel_path, lines in changed_by_path.items():
            abs_form = str((root_abs / rel_path).resolve())
            for key in {
                rel_path,
                rel_path.lstrip("./"),
                f"./{rel_path}",
                abs_form,
            }:
                norm_changed[key] = lines

        out: list[ContextItem] = []
        for item in items:
            lines_for_item = self._lookup_item_diff_lines(
                item.path_or_ref, norm_changed, root_abs
            )
            if not lines_for_item:
                out.append(item)
                continue
            symbol_range = sym_lines_by_item.get(id(item))
            if symbol_range is None:
                # Item backed by a file but no symbol-level line data —
                # cannot safely claim "overlaps changed lines". Skip.
                out.append(item)
                continue
            start, end = symbol_range
            if not symbol_overlaps_diff(start, end, lines_for_item):
                out.append(item)
                continue
            new_conf = min(0.95, item.confidence + 0.15)
            boosted = item.model_copy(update={"confidence": new_conf})
            out.append(boosted)
            if boosted_items_sink is not None:
                try:
                    boosted_items_sink.append(boosted.id)
                except Exception:  # noqa: BLE001 — telemetry never blocks ranking
                    pass
        return out

    @staticmethod
    def _lookup_item_diff_lines(
        path_or_ref: str,
        norm_changed: dict[str, set[int]],
        root_abs: Path,
    ) -> set[int]:
        """Return the changed-line set for *path_or_ref* across path forms."""
        if not path_or_ref:
            return set()
        if path_or_ref in norm_changed:
            return norm_changed[path_or_ref]
        # Absolute variant of a relative item path.
        try:
            abs_variant = str((root_abs / path_or_ref).resolve())
        except (OSError, RuntimeError):
            abs_variant = path_or_ref
        if abs_variant in norm_changed:
            return norm_changed[abs_variant]
        # Relative variant of an absolute item path.
        try:
            rel_variant = str(Path(path_or_ref).resolve().relative_to(root_abs))
        except (OSError, RuntimeError, ValueError):
            rel_variant = path_or_ref
        return norm_changed.get(rel_variant, set())

    def _resolve_symbol_line_ranges(
        self,
        items: list[ContextItem],
        db_path: Path | None,
    ) -> dict[int, tuple[int, int]]:
        """Return ``{id(item): (line_start, line_end)}`` for resolvable items.

        Mirrors :meth:`_resolve_symbol_ids` — same ``(file_path, name)``
        lookup but returns the line range instead of the symbol id.
        Returns an empty mapping on any failure so the boost path degrades
        gracefully.
        """
        if db_path is None or not items:
            return {}
        try:
            import sqlite3  # noqa: PLC0415

            if self._db_connection is not None:
                conn = self._db_connection
                owns_conn = False
                prev_factory = conn.row_factory
                conn.row_factory = sqlite3.Row
            else:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                owns_conn = True
                prev_factory = None
            try:
                by_repo: dict[str, list[ContextItem]] = {}
                for it in items:
                    by_repo.setdefault(it.repo or "default", []).append(it)

                result: dict[int, tuple[int, int]] = {}
                for repo_name, group in by_repo.items():
                    keys: list[tuple[str, str]] = []
                    item_by_key: dict[tuple[str, str], list[ContextItem]] = {}
                    for it in group:
                        name = it.title.split(" (")[0].strip()
                        if not name or not it.path_or_ref:
                            continue
                        key = (it.path_or_ref, name)
                        keys.append(key)
                        item_by_key.setdefault(key, []).append(it)
                    if not keys:
                        continue
                    placeholders = ",".join("(?, ?)" for _ in keys)
                    flat: list[str] = []
                    for fp, nm in keys:
                        flat.append(fp)
                        flat.append(nm)
                    rows = conn.execute(
                        f"""
                        WITH wanted(file_path, name) AS (VALUES {placeholders})
                        SELECT s.file_path, s.name, s.line_start, s.line_end
                        FROM symbols s
                        JOIN wanted w
                          ON s.file_path = w.file_path AND s.name = w.name
                        WHERE s.repo = ?
                        """,
                        (*flat, repo_name),
                    ).fetchall()
                    for r in rows:
                        key = (r["file_path"], r["name"])
                        ls = int(r["line_start"] or 0)
                        le = int(r["line_end"] or 0)
                        for it in item_by_key.get(key, []):
                            result[id(it)] = (ls, le)
                return result
            finally:
                if owns_conn:
                    conn.close()
                elif prev_factory is not None:
                    conn.row_factory = prev_factory
        except Exception:  # noqa: BLE001 — boost degrades gracefully
            return {}

    @staticmethod
    def _is_git_repo(root: Path) -> bool:
        """Return True iff ``git rev-parse --is-inside-work-tree`` succeeds."""
        import subprocess  # noqa: PLC0415

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
        except (FileNotFoundError, OSError):
            return False
        return result.returncode == 0

    def _warn_diff_aware_skipped(self, reason: str) -> None:
        """Emit the single stderr line when the diff-aware boost can't run."""
        try:
            print(
                f"context-router: diff-aware boost skipped: {reason}",
                file=sys.stderr,
            )
        except Exception:  # noqa: BLE001
            pass

    def _annotate(self, item: ContextItem) -> ContextItem:
        """Return a copy of *item* with the reason field populated.

        v3.2 outcome: function-level-reason — the orchestrator may have
        already set an upgraded reason string (e.g.
        ``"Modified `foo` lines 12-34"``) when the item is backed by a
        Symbol with known line data. Preserve that upgraded string; only
        fill the category fallback when ``reason`` is empty.
        """
        if item.reason:
            return item
        reason = _REASON.get(item.source_type, _DEFAULT_REASON)
        return item.model_copy(update={"reason": reason})

    def _enforce_budget(
        self, items: list[ContextItem], cap: int | None = None
    ) -> list[ContextItem]:
        """Trim *items* to the budget using a value-per-token ordering.

        Items are admitted greedily in descending ``confidence / est_tokens``
        order so a handful of small high-confidence items outrank a single
        large low-confidence one. ``is_first_of_type`` is preserved: at
        least one item per ``source_type`` survives even if admitting it
        slightly exceeds the budget. Returned items are re-sorted by raw
        confidence (descending) to match the original output contract.

        Args:
            items: Candidates to trim.
            cap: Optional explicit budget ceiling. When provided, overrides
                ``self._budget`` as the admission limit. Used by the memory
                sub-budget pass in ``rank()``.
        """
        budget = cap if cap is not None else self._budget
        admission_order = sorted(
            items,
            key=lambda i: (
                i.confidence / max(1, i.est_tokens),
                i.confidence,
            ),
            reverse=True,
        )

        admitted: list[ContextItem] = []
        accumulated = 0
        seen_types: set[str] = set()

        for item in admission_order:
            is_first_of_type = item.source_type not in seen_types
            fits = accumulated + item.est_tokens <= budget

            if fits or is_first_of_type:
                admitted.append(item)
                accumulated += item.est_tokens
                seen_types.add(item.source_type)

        return sorted(admitted, key=lambda i: i.confidence, reverse=True)
