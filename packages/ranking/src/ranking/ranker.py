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

import re
import threading

from contracts.models import ContextItem

_EMBED_MODEL: object | None = None
_EMBED_LOCK = threading.Lock()


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
# Maximum confidence boost from query matching
_MAX_BOOST = 0.50

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
        boosted = [self._apply_query_boost(item, query_tokens) for item in annotated]
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

    def _apply_query_boost(self, item: ContextItem, query_tokens: set[str]) -> ContextItem:
        """Boost *item* confidence if query tokens appear in its text fields.

        Checks title and excerpt. Boost is additive, proportional to the
        fraction of query tokens matched, capped at ``_MAX_BOOST`` (0.50),
        and never exceeds 0.95.

        Using additive boost for all confidence levels means a low-confidence
        "file" item (0.20) with a full query match reaches 0.70 — equal to
        blast_radius — so structurally-adjacent symbols don't crowd out
        query-relevant symbols in review mode.
        """
        if not query_tokens:
            return item
        # Use title + excerpt only — path_or_ref causes false positives when the
        # repository name happens to contain a query term (e.g. "fraud" in
        # "fraudguard-workspace" matching every file regardless of relevance).
        item_text = " ".join(
            filter(None, [item.title, item.excerpt])
        ).lower()
        matched = sum(1 for t in query_tokens if t in item_text)
        if matched == 0:
            return item
        ratio = matched / len(query_tokens)
        new_conf = min(0.95, item.confidence + ratio * _MAX_BOOST)
        return item.model_copy(update={"confidence": new_conf})

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
