"""Tests for ContextRanker: sorting, budget enforcement, reason annotation."""

from __future__ import annotations

from contracts.models import ContextItem
from ranking.ranker import ContextRanker, _REASON, _tokenize


def _item(
    *,
    source_type: str = "file",
    confidence: float = 0.5,
    est_tokens: int = 100,
    title: str = "sym",
) -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="test",
        path_or_ref="foo.py",
        title=title,
        excerpt="def foo(): ...",
        reason="",
        confidence=confidence,
        est_tokens=est_tokens,
    )


# -----------------------------------------------------------------------
# Basic behaviour
# -----------------------------------------------------------------------

def test_empty_input_returns_empty() -> None:
    ranker = ContextRanker(token_budget=1000)
    assert ranker.rank([], "q", "review") == []


def test_sorts_by_confidence_descending() -> None:
    items = [
        _item(confidence=0.2, title="low"),
        _item(confidence=0.9, title="high"),
        _item(confidence=0.5, title="mid"),
    ]
    result = ContextRanker(token_budget=100_000).rank(items, "", "review")
    titles = [i.title for i in result]
    assert titles == ["high", "mid", "low"]


def test_reason_populated_from_source_type() -> None:
    item = _item(source_type="changed_file")
    result = ContextRanker(token_budget=100_000).rank([item], "", "review")
    assert result[0].reason == _REASON["changed_file"]


def test_unknown_source_type_gets_default_reason() -> None:
    item = _item(source_type="mystery_type")
    result = ContextRanker(token_budget=100_000).rank([item], "", "review")
    assert result[0].reason  # non-empty fallback


# -----------------------------------------------------------------------
# Budget enforcement
# -----------------------------------------------------------------------

def test_budget_trims_lowest_confidence_items() -> None:
    items = [
        _item(confidence=0.9, est_tokens=50, title="a"),
        _item(confidence=0.5, est_tokens=50, title="b"),
        _item(confidence=0.1, est_tokens=50, title="c"),
    ]
    # budget = 100, only first two fit
    result = ContextRanker(token_budget=100).rank(items, "", "review")
    titles = {i.title for i in result}
    assert "a" in titles
    assert "b" in titles
    assert "c" not in titles


def test_zero_budget_returns_all_sorted() -> None:
    items = [_item(confidence=0.3), _item(confidence=0.9)]
    result = ContextRanker(token_budget=0).rank(items, "", "review")
    assert len(result) == 2
    assert result[0].confidence == 0.9


def test_budget_preserves_one_per_source_type() -> None:
    """Even if budget is tiny, at least one item per source_type survives."""
    items = [
        _item(source_type="changed_file", confidence=0.9, est_tokens=500, title="cf"),
        _item(source_type="file", confidence=0.2, est_tokens=500, title="f"),
    ]
    result = ContextRanker(token_budget=100).rank(items, "", "review")
    seen_types = {i.source_type for i in result}
    assert "changed_file" in seen_types
    assert "file" in seen_types


def test_all_items_fit_within_budget() -> None:
    items = [_item(est_tokens=10) for _ in range(5)]
    result = ContextRanker(token_budget=50).rank(items, "", "review")
    assert len(result) == 5


def test_query_boost_raises_confidence_for_matching_item() -> None:
    """Items whose title/excerpt contain query tokens get a confidence boost."""
    low_relevance = _item(confidence=0.5, title="unrelated_thing", est_tokens=10)
    high_relevance = ContextItem(
        source_type="file",
        repo="test",
        path_or_ref="ranker.py",
        title="ContextRanker (ranker.py)",
        excerpt="class ContextRanker:\nSorts and trims ContextItems to fit token budget.",
        reason="",
        confidence=0.5,
        est_tokens=20,
    )
    result = ContextRanker(token_budget=0).rank(
        [low_relevance, high_relevance],
        "add token budget to the ranker",
        "implement",
    )
    # high_relevance matches "ranker", "token", "budget" → boosted above low_relevance
    assert result[0].title == "ContextRanker (ranker.py)"
    assert result[0].confidence > 0.5


def test_query_boost_capped_at_0_95() -> None:
    """Confidence is never boosted above 0.95."""
    item = ContextItem(
        source_type="file",
        repo="test",
        path_or_ref="transactions.py",
        title="process_transaction (transactions.py)",
        excerpt="def process_transaction():\nProcess high value transaction fraud detection rule.",
        reason="",
        confidence=0.90,
        est_tokens=20,
    )
    result = ContextRanker(token_budget=0).rank(
        [item],
        "add fraud detection rule for high value transactions",
        "implement",
    )
    assert result[0].confidence <= 0.95


def test_tokenize_filters_short_tokens() -> None:
    tokens = _tokenize("add fraud detection rule for high value transactions")
    # All tokens >= 3 chars
    assert all(len(t) >= 3 for t in tokens)
    # Contains expected terms
    assert "fraud" in tokens
    assert "detection" in tokens
    assert "transactions" in tokens


def test_original_items_not_mutated() -> None:
    # Build item directly so we can set a non-empty reason
    item = ContextItem(
        source_type="file",
        repo="test",
        path_or_ref="foo.py",
        title="sym",
        excerpt="def foo(): ...",
        reason="original reason",
        confidence=0.5,
        est_tokens=10,
    )
    ContextRanker(token_budget=1000).rank([item], "", "review")
    # The original item should not be modified (model_copy is used internally)
    assert item.reason == "original reason"
