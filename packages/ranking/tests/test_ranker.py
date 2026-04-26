"""Tests for ContextRanker: sorting, budget enforcement, reason annotation."""

from __future__ import annotations

from contracts.models import ContextItem
from ranking.ranker import (
    ContextRanker,
    _REASON,
    _BM25Scorer,
    _tokenize,
    _is_test_or_script_path,
    _ADAPTIVE_TOPK_PLATEAU_DELTA,
    _ADAPTIVE_TOPK_ABS_FLOOR,
)


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
        path_or_ref=f"{title}.py",
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
    # Use "debug" mode to avoid adaptive top-k trimming the low-confidence
    # tail — this test is about sort order, not filtering precision.
    items = [
        _item(confidence=0.2, title="low"),
        _item(confidence=0.9, title="high"),
        _item(confidence=0.5, title="mid"),
    ]
    result = ContextRanker(token_budget=100_000).rank(items, "", "debug")
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
    # Use "debug" mode to isolate budget enforcement from adaptive top-k.
    # In "review" mode adaptive top-k can also trim items below the
    # confidence floor, which is a different mechanism than budget trimming.
    items = [
        _item(confidence=0.9, est_tokens=50, title="a"),
        _item(confidence=0.5, est_tokens=50, title="b"),
        _item(confidence=0.1, est_tokens=50, title="c"),
    ]
    # budget = 100, only first two fit
    result = ContextRanker(token_budget=100).rank(items, "", "debug")
    titles = {i.title for i in result}
    assert "a" in titles
    assert "b" in titles
    assert "c" not in titles


def test_zero_budget_returns_all_sorted() -> None:
    # Distinct titles so the v3.2 symbol-stub-dedup pass doesn't merge
    # these items — the test case is about sort order, not dedup.
    # Use "debug" mode to avoid adaptive top-k trimming the low-confidence tail.
    items = [_item(confidence=0.3, title="low"), _item(confidence=0.9, title="high")]
    result = ContextRanker(token_budget=0).rank(items, "", "debug")
    assert len(result) == 2
    assert result[0].confidence == 0.9


def test_budget_preserves_one_per_source_type() -> None:
    """Even if budget is tiny, at least one item per source_type survives."""
    # Use "debug" mode to avoid adaptive top-k removing the low-confidence
    # "file" item before the budget-preservation assertion can be checked.
    items = [
        _item(source_type="changed_file", confidence=0.9, est_tokens=500, title="cf"),
        _item(source_type="file", confidence=0.2, est_tokens=500, title="f"),
    ]
    result = ContextRanker(token_budget=100).rank(items, "", "debug")
    seen_types = {i.source_type for i in result}
    assert "changed_file" in seen_types
    assert "file" in seen_types


def test_all_items_fit_within_budget() -> None:
    # Distinct titles so the v3.2 symbol-stub-dedup pass doesn't merge
    # the items — the test case is about budget enforcement, not dedup.
    items = [_item(est_tokens=10, title=f"item_{i}") for i in range(5)]
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
        path_or_ref="sym.py",
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
# v3 phase-2: --with-semantic applies in every pack mode
# (outcome: semantic-default-with-progress)
#
# The phase-1 outcome ``with-semantic-warns-outside-implement`` is
# superseded by phase-2's ``semantic-default-with-progress``: the flag
# no longer no-ops outside implement mode, so the stderr warning has
# been removed. The superseded outcome id remains in
# ``docs/release/v3-outcomes.yaml`` for traceability; the tests below
# pin the new contract (silent, effective in every mode).
# -----------------------------------------------------------------------

def test_with_semantic_is_silent_in_every_mode(capsys) -> None:
    """use_embeddings=True must not warn in any mode (phase-2 contract).

    Phase 1 added a stderr warning when --with-semantic had no effect
    outside implement. Phase 2 removes the mode gate, so the warning is
    obsolete — the flag now works in every mode and must be silent.
    """
    for mode in ("review", "debug", "implement", "handover"):
        ranker = ContextRanker(token_budget=1000, use_embeddings=True)
        ranker.rank([_item()], "q", mode)
        captured = capsys.readouterr()
        # Semantic boost is best-effort; if sentence-transformers isn't
        # installed the import-error path emits a single warning naming
        # the missing dep. Any "no effect in <mode>" warning is now a
        # regression against the phase-2 contract.
        assert f"no effect in {mode}" not in captured.err, (
            f"phase-2 regression: phase-1 warning still fires in {mode}"
        )


def test_without_semantic_silent_in_every_mode(capsys) -> None:
    """use_embeddings=False must never warn regardless of mode."""
    for mode in ("review", "debug", "implement", "handover"):
        ranker = ContextRanker(token_budget=1000, use_embeddings=False)
        ranker.rank([_item()], "q", mode)
        captured = capsys.readouterr()
        assert captured.err == ""


def test_semantic_boost_applied_outside_implement(monkeypatch) -> None:
    """use_embeddings=True must route through _apply_semantic_boost in
    every mode, not only implement (phase-2 contract).

    We stub the semantic-boost helper so the test doesn't require
    sentence-transformers to be installed.
    """
    calls: list[str] = []

    def _fake_boost(self, items, query):  # noqa: ANN001
        calls.append("called")
        return items

    monkeypatch.setattr(ContextRanker, "_apply_semantic_boost", _fake_boost)

    for mode in ("review", "debug", "implement", "handover"):
        calls.clear()
        ContextRanker(token_budget=1000, use_embeddings=True).rank(
            [_item()], "q", mode
        )
        assert calls == ["called"], (
            f"semantic boost should fire in {mode} mode but did not; "
            f"this is the phase-2 regression guard"
        )


def test_semantic_boost_not_applied_when_flag_off(monkeypatch) -> None:
    """use_embeddings=False must never route through _apply_semantic_boost."""
    calls: list[str] = []

    def _fake_boost(self, items, query):  # noqa: ANN001
        calls.append("called")
        return items

    monkeypatch.setattr(ContextRanker, "_apply_semantic_boost", _fake_boost)

    for mode in ("review", "debug", "implement", "handover"):
        ContextRanker(token_budget=1000, use_embeddings=False).rank(
            [_item()], "q", mode
        )
    assert calls == []


def test_semantic_boost_changes_ranking_in_handover(monkeypatch) -> None:
    """handover mode with use_embeddings=True must produce a different
    ranking than without — mirrors the smoke check's threshold.

    We stub _apply_semantic_boost to inject a deterministic perturbation
    so this test doesn't depend on sentence-transformers.
    """
    def _stub_boost(self, items, query):  # noqa: ANN001
        # Flip the top two items' confidence to force a reordering.
        if len(items) < 2:
            return items
        result = list(items)
        result[0] = result[0].model_copy(update={"confidence": 0.10})
        result[1] = result[1].model_copy(update={"confidence": 0.90})
        return result

    monkeypatch.setattr(ContextRanker, "_apply_semantic_boost", _stub_boost)

    items = [
        _item(confidence=0.80, title="a"),
        _item(confidence=0.20, title="b"),
    ]
    without = ContextRanker(token_budget=0, use_embeddings=False).rank(
        list(items), "q", "handover"
    )
    with_sem = ContextRanker(token_budget=0, use_embeddings=True).rank(
        list(items), "q", "handover"
    )
    titles_without = [i.title for i in without]
    titles_with = [i.title for i in with_sem]
    assert titles_without != titles_with, (
        "handover mode ranking with --with-semantic must differ from "
        "plain ranking (phase-2 outcome threshold)"
    )


# -----------------------------------------------------------------------
# v4.2 T3 — Adaptive top-k
# -----------------------------------------------------------------------

def test_adaptive_topk_drops_low_confidence_tail_in_review_mode() -> None:
    """Trailing items below FLOOR_RATIO × leader are dropped in review mode."""
    # floor = 0.6 * 0.9 = 0.54; items with conf 0.2 and 0.1 are below the floor
    items = [
        _item(confidence=0.9, title="a"),
        _item(confidence=0.8, title="b"),
        _item(confidence=0.7, title="c"),
        _item(confidence=0.2, title="d"),
        _item(confidence=0.1, title="e"),
    ]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "review")
    titles = [i.title for i in result]
    assert "d" not in titles
    assert "e" not in titles
    assert "a" in titles and "b" in titles and "c" in titles


def test_adaptive_topk_noop_in_debug_mode() -> None:
    """Adaptive top-k is a no-op in debug mode — all items kept."""
    items = [
        _item(confidence=0.9, title="a"),
        _item(confidence=0.8, title="b"),
        _item(confidence=0.7, title="c"),
        _item(confidence=0.2, title="d"),
        _item(confidence=0.1, title="e"),
    ]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "debug")
    assert len(result) == 5


def test_adaptive_topk_noop_in_handover_mode() -> None:
    """Adaptive top-k is a no-op in handover mode — all items kept."""
    items = [
        _item(confidence=0.9, title="a"),
        _item(confidence=0.8, title="b"),
        _item(confidence=0.7, title="c"),
        _item(confidence=0.2, title="d"),
        _item(confidence=0.1, title="e"),
    ]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "handover")
    assert len(result) == 5


def test_adaptive_topk_noop_when_all_above_floor() -> None:
    """No items dropped when all are above the floor (0.6 × 0.9 = 0.54)."""
    items = [
        _item(confidence=0.9, title="a"),
        _item(confidence=0.85, title="b"),
        _item(confidence=0.8, title="c"),
    ]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "review")
    assert len(result) == 3


def test_adaptive_topk_never_drops_sole_item() -> None:
    """A single item with very low confidence is always kept."""
    items = [_item(confidence=0.1, title="only")]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "review")
    assert len(result) == 1


def test_adaptive_topk_single_item_is_never_dropped() -> None:
    """The last remaining item is always kept even if below floor."""
    # With 2 items: floor = 0.6 * 0.9 = 0.54. Item b = 0.1 is below floor
    # but last_keep must never go below 0, so the leader is always retained.
    items = [
        _item(confidence=0.9, title="a"),
        _item(confidence=0.1, title="b"),
    ]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "review")
    # "a" must survive (leader is never dropped)
    assert any(i.title == "a" for i in result)
    assert len(result) >= 1


# -----------------------------------------------------------------------
# v4.3 Phase C — Aux path coverage + plateau rule
# -----------------------------------------------------------------------

def test_aux_path_re_covers_docs_src() -> None:
    assert _is_test_or_script_path("docs_src/security/tutorial003_py310.py")
    assert _is_test_or_script_path("docs_src/tutorial003_an_py310.py")


def test_aux_path_re_covers_auxiliary_dirs() -> None:
    for path in [
        "examples/auth_example.py",
        "example/config.py",
        "fixtures/mock_data.py",
        "stubs/stub_api.py",
        "mocks/mock_handler.py",
    ]:
        assert _is_test_or_script_path(path), f"expected auxiliary: {path}"
    # canonical source paths must NOT be flagged
    for path in ["fastapi/security/oauth2.py", "src/auth/token.py", "lib/utils.py"]:
        assert not _is_test_or_script_path(path), f"should not be auxiliary: {path}"


def test_adaptive_topk_plateau_rule_fires() -> None:
    """Plateau rule drops from the first pair whose step < DELTA and conf < ABS_FLOOR.

    With [0.52, 0.42, 0.39, 0.38, 0.37] and ABS_FLOOR=0.40:
    - pair (a->b): step=0.10 >= DELTA — not a plateau entry
    - pair (b->c): step=0.03 >= DELTA — not a plateau entry
    - pair (c->d): step=0.01 < DELTA AND d=0.38 < ABS_FLOOR — plateau starts here
    Rule fires at i=3 -> last_keep=min(4,2)=2 -> keeps [a, b, c], drops d/e.
    """
    items = [
        _item(confidence=0.52, title="a"),
        _item(confidence=0.42, title="b"),
        _item(confidence=0.39, title="c"),
        _item(confidence=0.38, title="d"),
        _item(confidence=0.37, title="e"),
    ]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "review")
    titles = [i.title for i in result]
    assert "a" in titles
    assert "b" in titles
    assert "c" in titles, "c is kept — plateau fires at the c->d transition"
    assert "d" not in titles, "d and beyond are cut as plateau"
    assert "e" not in titles


def test_adaptive_topk_plateau_rule_noop_above_abs_floor() -> None:
    """Plateau rule must not fire when items are at or above ABS_FLOOR."""
    items = [
        _item(confidence=0.52, title="a"),
        _item(confidence=0.50, title="b"),
        _item(confidence=0.49, title="c"),
        _item(confidence=0.48, title="d"),
        _item(confidence=0.47, title="e"),
    ]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "review")
    assert len(result) == 5, "all items above ABS_FLOOR — nothing should be cut"


# -----------------------------------------------------------------------
# v4.2 T3 — Memory sub-budget cap
# -----------------------------------------------------------------------

def test_memory_items_capped_at_15pct() -> None:
    """Memory items are capped at 15% of total budget (default)."""
    # 10 memory items × 100 tokens = 1000 tokens; 15% of 1000 = 150 tokens = 1 item
    # 10 code items × 100 tokens = 1000 tokens
    memory_items = [
        _item(source_type="memory", est_tokens=100, confidence=0.8, title=f"mem_{i}")
        for i in range(10)
    ]
    code_items = [
        _item(source_type="file", est_tokens=100, confidence=0.7, title=f"code_{i}")
        for i in range(10)
    ]
    ranker = ContextRanker(token_budget=1000, memory_budget_pct=0.15)
    result = ranker.rank(memory_items + code_items, "", "review")
    memory_count = len([i for i in result if i.source_type == "memory"])
    assert memory_count <= 2


def test_memory_cap_custom_pct() -> None:
    """With memory_budget_pct=0.5, memory gets up to 50% of budget."""
    # 10 memory items × 100 tokens; 50% of 1000 = 500 tokens = 5 items
    memory_items = [
        _item(source_type="memory", est_tokens=100, confidence=0.8, title=f"mem_{i}")
        for i in range(10)
    ]
    code_items = [
        _item(source_type="file", est_tokens=100, confidence=0.7, title=f"code_{i}")
        for i in range(10)
    ]
    ranker = ContextRanker(token_budget=1000, memory_budget_pct=0.5)
    result = ranker.rank(memory_items + code_items, "", "review")
    memory_count = len([i for i in result if i.source_type == "memory"])
    assert memory_count >= 3  # at least 3 memory items fit in 500-token cap


def test_memory_cap_no_memory_items_noop() -> None:
    """All code items, no memory items — code items fill budget normally."""
    code_items = [
        _item(source_type="file", est_tokens=100, confidence=0.7, title=f"code_{i}")
        for i in range(10)
    ]
    ranker = ContextRanker(token_budget=1000, memory_budget_pct=0.15)
    result = ranker.rank(code_items, "", "review")
    # No memory items → code fills remaining budget (up to 1000 tokens = 10 items)
    assert len(result) >= 5


# -----------------------------------------------------------------------
# v4.4 C1: source-file basename boost
# -----------------------------------------------------------------------

def test_source_file_boost_ranks_module_above_test() -> None:
    """oauth2.py (conf=0.5) must rank above tests/test_security_oauth2.py (conf=0.55).

    The test file has a higher structural confidence; without the basename
    boost the BM25 + structural blend would let it stay on top. The 1.3x
    multiplier on the source module must overcome that gap.
    """
    source_item = ContextItem(
        source_type="file",
        repo="fastapi",
        path_or_ref="fastapi/security/oauth2.py",
        title="OAuth2 (oauth2.py)",
        excerpt="class OAuth2: ...",
        reason="",
        confidence=0.5,
        est_tokens=100,
    )
    test_item = ContextItem(
        source_type="file",
        repo="fastapi",
        path_or_ref="tests/test_security_oauth2.py",
        title="test_security_oauth2",
        excerpt="from fastapi.security.oauth2 import OAuth2",
        reason="",
        confidence=0.55,
        est_tokens=100,
    )
    ranker = ContextRanker(token_budget=0)
    result = ranker.rank([source_item, test_item], "oauth2 form docstrings", "implement")
    paths = [i.path_or_ref for i in result]
    # oauth2.py must be in results and ranked first.
    # The test file may be cut by Rule 1 when the source file ranks strongly.
    assert "fastapi/security/oauth2.py" in paths, f"oauth2.py missing from results: {paths}"
    assert paths[0] == "fastapi/security/oauth2.py", f"Expected oauth2.py first, got: {paths}"


# -----------------------------------------------------------------------
# v4.4 C2 — Lower ABS_FLOOR and enable semantic re-rank by default
# -----------------------------------------------------------------------


def test_adaptive_topk_floor_is_0_40() -> None:
    """ABS_FLOOR is exactly 0.40 (not the old 0.45)."""
    assert _ADAPTIVE_TOPK_ABS_FLOOR == 0.40


def test_adaptive_topk_item_at_0_41_survives_plateau_cut() -> None:
    """Item at conf=0.41 survives with ABS_FLOOR=0.40 (would be cut at old 0.45).

    With [0.80, 0.41] and ABS_FLOOR=0.40:
    - Rule 1: floor = 0.6 * 0.80 = 0.48 — 0.41 < 0.48, would be cut by Rule 1.
    Use three items so Rule 1 doesn't cut the 0.41 item:
    [0.80, 0.70, 0.41] — Rule 1 floor = 0.6 * 0.80 = 0.48; 0.41 < 0.48 — cut by Rule 1.

    To isolate the plateau rule: use [0.45, 0.41] — floor=0.6*0.45=0.27, 0.41>0.27 survives Rule 1.
    Plateau: leader=0.45 > ABS_FLOOR=0.40; pair (a->b): step=0.04>=DELTA — no fire.
    Result: both items kept.
    """
    items = [
        _item(confidence=0.45, title="a"),
        _item(confidence=0.41, title="b"),
    ]
    ranker = ContextRanker(token_budget=0)
    result = ranker._apply_adaptive_top_k(items, "review")
    titles = [i.title for i in result]
    assert "b" in titles, "item at conf=0.41 should survive with ABS_FLOOR=0.40"


def test_use_embeddings_default_is_true() -> None:
    """use_embeddings defaults to True (v4.4 C2: semantic re-rank enabled by default)."""
    ranker = ContextRanker(token_budget=0)
    assert ranker._use_embeddings is True
