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

from contracts.models import ContextItem

# Minimum characters in a query token to be used for boosting (filters stop words)
_MIN_TOKEN_LEN = 3
# Maximum confidence boost from query matching
_MAX_BOOST = 0.30

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

    def __init__(self, token_budget: int = 8_000) -> None:
        """Initialise the ranker with a token budget.

        Args:
            token_budget: Hard upper limit on total ``est_tokens`` in the
                returned item list.  0 means unlimited.
        """
        self._budget = token_budget

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
        3. Sort by ``confidence`` descending.
        4. Trim to token budget while keeping at least one item per
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
        sorted_items = sorted(boosted, key=lambda i: i.confidence, reverse=True)

        if self._budget <= 0:
            return sorted_items

        return self._enforce_budget(sorted_items)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_query_boost(self, item: ContextItem, query_tokens: set[str]) -> ContextItem:
        """Boost *item* confidence if query tokens appear in its text fields.

        Checks title, excerpt, and signature (from ``path_or_ref`` label).
        Boost is proportional to the fraction of query tokens matched,
        capped at ``_MAX_BOOST`` (0.30), and never exceeds 0.95.
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
        boost = min(_MAX_BOOST, (matched / len(query_tokens)) * _MAX_BOOST)
        new_conf = min(0.95, item.confidence + boost)
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
