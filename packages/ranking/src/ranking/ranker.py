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
import re
import threading
from collections import Counter as _Counter

from contracts.models import ContextItem

_EMBED_MODEL: object | None = None
_EMBED_LOCK = threading.Lock()


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


def _get_embed_model() -> object:
    """Lazy-load the sentence-transformers model; returns False if unavailable."""
    global _EMBED_MODEL
    if _EMBED_MODEL is not None:
        return _EMBED_MODEL
    with _EMBED_LOCK:
        if _EMBED_MODEL is None:
            try:
                from sentence_transformers import SentenceTransformer  # type: ignore[import]
                _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception:
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
}

_DEFAULT_REASON = "Included in context pack"


def _tokenize(text: str) -> set[str]:
    """Return lowercase tokens from *text* that are at least _MIN_TOKEN_LEN chars."""
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= _MIN_TOKEN_LEN}


class ContextRanker:
    """Sorts and trims ContextItems to fit within a token budget.

    Implements the ``Ranker`` protocol defined in ``contracts.interfaces``.

    Args:
        token_budget: Maximum total estimated tokens for the output pack.
            Pass 0 to disable budget enforcement (return all items sorted).
    """

    def __init__(self, token_budget: int = 8_000, use_embeddings: bool = False) -> None:
        """Initialise the ranker with a token budget.

        Args:
            token_budget: Hard upper limit on total ``est_tokens`` in the
                returned item list.  0 means unlimited.
            use_embeddings: If True, apply semantic similarity boosting via
                sentence-transformers (requires ``pip install sentence-transformers``).
                Defaults to False to avoid the model download on first run.
        """
        self._budget = token_budget
        self._use_embeddings = use_embeddings

    def rank(
        self,
        items: list[ContextItem],
        query: str,
        mode: str,  # noqa: ARG002 — reserved for mode-specific post-processing
    ) -> list[ContextItem]:
        """Rank *items* and enforce the token budget.

        Steps:
        1. Annotate each item's ``reason`` from its ``source_type``.
        2. Apply query-relevance confidence boost (keyword overlap).
        3. Optionally apply semantic similarity boost (if use_embeddings=True).
        4. Sort by ``confidence`` descending.
        5. Trim to token budget while keeping at least one item per
           ``source_type`` (so every category of evidence is represented).

        Args:
            items: Pre-scored ContextItem candidates.
            query: Free-text task description used for relevance boosting.
            mode: Task mode (reserved for future use).

        Returns:
            Ranked and budget-enforced list of ContextItems.
        """
        if not items:
            return []

        query_tokens = _tokenize(query)
        annotated = [self._annotate(item) for item in items]
        boosted = self._apply_bm25_boost(annotated, query_tokens)
        if self._use_embeddings:
            boosted = self._apply_semantic_boost(boosted, query)
        sorted_items = sorted(boosted, key=lambda i: i.confidence, reverse=True)

        if self._budget <= 0:
            return sorted_items

        return self._enforce_budget(sorted_items)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_semantic_boost(self, items: list[ContextItem], query: str) -> list[ContextItem]:
        """Boost items using cosine similarity from sentence-transformers.

        Only runs when ``use_embeddings=True`` and the model is available.
        Items with similarity > 0.3 receive up to +0.20 confidence boost.
        """
        if not query or not items:
            return items
        model = _get_embed_model()
        if not model:
            return items
        try:
            import numpy as np  # type: ignore[import]
            texts = [f"{i.title} {i.excerpt}" for i in items]
            query_emb = model.encode([query], normalize_embeddings=True)
            item_embs = model.encode(texts, normalize_embeddings=True, batch_size=32)
            similarities = (item_embs @ query_emb.T).flatten()
            result = []
            for item, sim in zip(items, similarities):
                sim_f = float(sim)
                if sim_f > 0.3:
                    boost = min(0.20, sim_f * 0.20)
                    new_conf = min(0.95, item.confidence + boost)
                    result.append(item.model_copy(update={"confidence": new_conf}))
                else:
                    result.append(item)
            return result
        except Exception:
            return items

    def _apply_bm25_boost(self, items: list[ContextItem], query_tokens: set[str]) -> list[ContextItem]:
        """Re-score items using BM25 relevance combined with structural confidence.

        Formula: ``final_conf = min(0.95, 0.6 × structural_conf + 0.4 × bm25_score)``

        *bm25_score* is normalized to [0, 1] across all candidates so the most
        BM25-relevant item gets the full 0.40 bonus.  Items with no query
        match get a score of 0, so their final confidence is 60% of their
        structural score — they remain in the pack but yield priority to
        query-relevant symbols.

        Using title + excerpt only — path_or_ref causes false positives when
        the repository name happens to contain a query term.
        """
        if not query_tokens or not items:
            return items
        corpus = [f"{i.title} {i.excerpt}" for i in items]
        scorer = _BM25Scorer(corpus)
        bm25_scores = scorer.scores_normalized(query_tokens)
        result = []
        for item, bm25 in zip(items, bm25_scores):
            new_conf = min(0.95, 0.6 * item.confidence + 0.4 * bm25)
            result.append(item.model_copy(update={"confidence": new_conf}))
        return result

    def _annotate(self, item: ContextItem) -> ContextItem:
        """Return a copy of *item* with the reason field populated."""
        reason = _REASON.get(item.source_type, _DEFAULT_REASON)
        return item.model_copy(update={"reason": reason})

    def _enforce_budget(self, items: list[ContextItem]) -> list[ContextItem]:
        """Trim *items* (already sorted desc by confidence) to the budget.

        Guarantees that at least one item per ``source_type`` is kept even
        if doing so slightly exceeds the budget (a single item can never be
        rejected if it is the only representative of its category).

        Args:
            items: Sorted list of ContextItems (highest confidence first).

        Returns:
            Filtered list that fits within the token budget (best effort).
        """
        result: list[ContextItem] = []
        accumulated = 0
        seen_types: set[str] = set()

        for item in items:
            is_first_of_type = item.source_type not in seen_types
            fits = accumulated + item.est_tokens <= self._budget

            if fits or is_first_of_type:
                result.append(item)
                accumulated += item.est_tokens
                seen_types.add(item.source_type)

        return result
