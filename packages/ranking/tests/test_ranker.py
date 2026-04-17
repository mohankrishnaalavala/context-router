"""Tests for ContextRanker: sorting, budget enforcement, reason annotation."""

from __future__ import annotations

from contracts.models import ContextItem
from ranking.ranker import ContextRanker, _REASON, _BM25Scorer, _tokenize


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


def test_knapsack_prefers_many_small_over_one_large() -> None:
    """Four 400-token 0.7-confidence items should beat one 2000-token 0.9."""
    items = [_item(source_type="big", confidence=0.9, est_tokens=2000, title="big")]
    items += [
        _item(source_type="small", confidence=0.7, est_tokens=400, title=f"s{i}")
        for i in range(4)
    ]
    result = ContextRanker(token_budget=2000).rank(items, "", "review")
    titles = {i.title for i in result}
    assert "s0" in titles and "s1" in titles and "s2" in titles and "s3" in titles
    assert "big" in titles
    admitted_small_tokens = sum(i.est_tokens for i in result if i.source_type == "small")
    assert admitted_small_tokens >= 1600


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


def test_bm25_boost_for_low_confidence_item() -> None:
    """BM25 scoring raises low-confidence items that match the query."""
    item = ContextItem(
        source_type="file", repo="test", path_or_ref="ranker.py",
        title="ContextRanker (ranker.py)",
        excerpt="class ContextRanker:\nSorts ContextItems to fit token budget.",
        reason="", confidence=0.20, est_tokens=20,
    )
    result = ContextRanker(token_budget=0).rank(
        [item], "token budget ranker", "implement"
    )
    # BM25 formula: 0.6 * 0.20 + 0.4 * bm25_score
    # Single item corpus → normalized bm25 = 1.0 → result = 0.12 + 0.40 = 0.52
    assert result[0].confidence > 0.20


def test_bm25_boost_for_high_confidence_item() -> None:
    """BM25 scoring does not exceed 0.95 ceiling for high-confidence items."""
    item = ContextItem(
        source_type="contract", repo="test", path_or_ref="ranker.py",
        title="Ranker (interfaces.py)",
        excerpt="class Ranker token budget",
        reason="", confidence=0.80, est_tokens=20,
    )
    result = ContextRanker(token_budget=0).rank(
        [item], "token budget ranker", "implement"
    )
    # BM25: 0.6 * 0.80 + 0.4 * 1.0 = 0.88
    assert result[0].confidence <= 0.95
    assert result[0].confidence >= 0.48  # at minimum 60% of structural


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


# -----------------------------------------------------------------------
# P4 — BM25 scorer unit tests
# -----------------------------------------------------------------------

class TestBM25Scorer:
    def test_empty_corpus_returns_empty_scores(self) -> None:
        scorer = _BM25Scorer([])
        assert scorer.scores_normalized({"query"}) == []

    def test_empty_query_tokens_returns_zeros(self) -> None:
        scorer = _BM25Scorer(["hello world", "another doc"])
        scores = scorer.scores_normalized(set())
        assert scores == [0.0, 0.0]

    def test_single_doc_corpus_gets_score_one(self) -> None:
        scorer = _BM25Scorer(["authentication token verify"])
        scores = scorer.scores_normalized({"authentication"})
        assert scores == [1.0]

    def test_scores_normalized_range_0_to_1(self) -> None:
        docs = ["the quick brown fox", "lazy dog", "quick authentication token"]
        scorer = _BM25Scorer(docs)
        scores = scorer.scores_normalized({"quick", "authentication"})
        assert len(scores) == 3
        assert all(0.0 <= s <= 1.0 for s in scores)
        assert max(scores) == 1.0  # at least one document equals 1.0

    def test_relevant_doc_ranks_higher(self) -> None:
        scorer = _BM25Scorer([
            "completely unrelated document about dogs",
            "AuthManager verify_token authentication handler class",
        ])
        scores = scorer.scores_normalized({"authentication", "verify"})
        assert scores[1] > scores[0]

    def test_no_doc_matches_query_all_zeros(self) -> None:
        scorer = _BM25Scorer(["foo bar baz", "qux quux"])
        scores = scorer.scores_normalized({"nonexistent", "term"})
        assert scores == [0.0, 0.0]


class TestBM25Integration:
    def test_bm25_ranks_matching_item_first(self) -> None:
        """Item with query-matching content should rank above unrelated item."""
        unrelated = _item(confidence=0.5, title="DatabaseMigration schema_v3")
        relevant = ContextItem(
            source_type="file", repo="test", path_or_ref="auth.py",
            title="AuthManager (auth.py)",
            excerpt="class AuthManager:\n  def verify_token(self, token): ...",
            reason="", confidence=0.5, est_tokens=30,
        )
        result = ContextRanker(token_budget=0).rank(
            [unrelated, relevant], "authentication verify token", "implement"
        )
        assert result[0].title == "AuthManager (auth.py)"

    def test_bm25_no_match_uses_structural_conf(self) -> None:
        """Items with no query match get 0.6 × structural confidence."""
        item = _item(confidence=0.80, title="xyz_unrelated abc")
        result = ContextRanker(token_budget=0).rank(
            [item], "completely_different_query", "review"
        )
        # bm25 = 0.0, so new_conf = 0.6 * 0.80 + 0.4 * 0.0 = 0.48
        assert abs(result[0].confidence - 0.48) < 0.05

    def test_bm25_scores_capped_at_0_95(self) -> None:
        """No item exceeds 0.95 confidence."""
        items = [
            ContextItem(
                source_type="changed_file", repo="test", path_or_ref="auth.py",
                title="AuthManager authenticate verify token",
                excerpt="authenticate verify token authentication",
                reason="", confidence=0.95, est_tokens=20,
            )
        ]
        result = ContextRanker(token_budget=0).rank(
            items, "authenticate verify token", "review"
        )
        assert result[0].confidence <= 0.95


# -----------------------------------------------------------------------
# P5 — call_chain source_type in _REASON
# -----------------------------------------------------------------------

def test_call_chain_reason_in_reason_dict() -> None:
    """call_chain source_type must have a human-readable reason."""
    assert "call_chain" in _REASON
    assert len(_REASON["call_chain"]) > 10  # non-trivial string


def test_call_chain_item_gets_annotated_reason() -> None:
    item = ContextItem(
        source_type="call_chain", repo="test", path_or_ref="helper.py",
        title="helper.py (call chain depth 2)",
        excerpt="", reason="", confidence=0.315, est_tokens=50,
    )
    result = ContextRanker(token_budget=0).rank([item], "", "debug")
    assert result[0].reason == _REASON["call_chain"]


# -----------------------------------------------------------------------
# v3 phase-1: --with-semantic outside implement mode emits a warning
# (outcome: with-semantic-warns-outside-implement)
# -----------------------------------------------------------------------

def test_with_semantic_warns_in_handover_mode(capsys) -> None:
    """use_embeddings=True + mode=handover should warn to stderr."""
    ranker = ContextRanker(token_budget=1000, use_embeddings=True)
    ranker.rank([_item()], "q", "handover")
    captured = capsys.readouterr()
    assert "no effect in handover" in captured.err
    assert captured.out == ""


def test_with_semantic_silent_in_implement_mode(capsys) -> None:
    """use_embeddings=True + mode=implement must NOT warn (normal case)."""
    ranker = ContextRanker(token_budget=1000, use_embeddings=True)
    ranker.rank([_item()], "q", "implement")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_without_semantic_silent_in_handover_mode(capsys) -> None:
    """use_embeddings=False must NOT warn regardless of mode."""
    ranker = ContextRanker(token_budget=1000, use_embeddings=False)
    ranker.rank([_item()], "q", "handover")
    captured = capsys.readouterr()
    assert captured.err == ""


def test_with_semantic_warns_once_per_rank_call(capsys) -> None:
    """Two sequential rank() calls each emit exactly one warning line.

    Regression guard: the warning must be emitted once per rank() call,
    not per item and not zero (no over-suppression via a 'warned' flag).
    """
    ranker = ContextRanker(token_budget=1000, use_embeddings=True)
    items = [_item(title="a"), _item(title="b"), _item(title="c")]
    ranker.rank(items, "q", "review")
    ranker.rank(items, "q", "review")
    captured = capsys.readouterr()
    warning_lines = [
        line for line in captured.err.splitlines()
        if "no effect in review" in line
    ]
    assert len(warning_lines) == 2, (
        f"expected exactly 2 warnings (one per rank call), got {len(warning_lines)}: "
        f"{warning_lines!r}"
    )
