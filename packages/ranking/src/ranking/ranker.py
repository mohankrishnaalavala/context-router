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

from contracts.models import ContextItem

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
}

_DEFAULT_REASON = "Included in context pack"


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
        query: str,  # noqa: ARG002 — reserved for future query-match boosting
        mode: str,  # noqa: ARG002 — reserved for mode-specific post-processing
    ) -> list[ContextItem]:
        """Rank *items* and enforce the token budget.

        Steps:
        1. Annotate each item's ``reason`` from its ``source_type``.
        2. Sort by ``confidence`` descending.
        3. Trim to token budget while keeping at least one item per
           ``source_type`` (so every category of evidence is represented).

        Args:
            items: Pre-scored ContextItem candidates.
            query: Free-text task description (reserved for future use).
            mode: Task mode (reserved for future use).

        Returns:
            Ranked and budget-enforced list of ContextItems.
        """
        if not items:
            return []

        annotated = [self._annotate(item) for item in items]
        sorted_items = sorted(annotated, key=lambda i: i.confidence, reverse=True)

        if self._budget <= 0:
            return sorted_items

        return self._enforce_budget(sorted_items)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
