"""Tests for v4.4.2: post-rerank source-preference prior.

The cross-encoder rerank in v4.4 (Phase 2) blends 0.5 * structural with
0.5 * cross-encoder probability. On tasks where a test file's name
quotes the query verbatim (e.g. fastapi T1's ``test_compex_doc.py``
mentioning ``client_secret``), the lexical-overlap boost was strong
enough to override the structural source-preference prior — pushing
production sources like ``oauth2.py`` out of the pack entirely.

v4.4.2 restores the v4.1 asymmetry as a multiplicative pass *after* the
blend (and before the [0, 0.95] clamp): source paths * 1.15, test/aux
paths * 0.85. Cross still reorders within a class.

These tests target ``_apply_cross_encoder_rerank`` directly rather than
the full ``rank()`` pipeline so the BM25 + source-file boosts that run
upstream don't perturb the structural input we're asserting on.
"""

from __future__ import annotations

from typing import Any

import pytest

# The post-rerank prior these tests assert on only takes effect inside
# ``_apply_cross_encoder_rerank``'s sigmoid pass, which requires numpy.
# When numpy is absent (CI's bare workspace install — sentence-transformers
# is the transitive carrier) the rerank silent-degrades to a no-op and the
# prior is never reached. Skip the whole module in that case rather than
# assert numeric outcomes against the no-op path.
pytest.importorskip("numpy")

from contracts.models import ContextItem
from ranking.ranker import (
    ContextRanker,
    _RERANK_SOURCE_PRIOR_MULT,
    _RERANK_TEST_PRIOR_MULT,
)


def _item(
    *,
    path: str,
    title: str = "sym",
    confidence: float = 0.5,
    excerpt: str = "def foo(): ...",
    est_tokens: int = 80,
    source_type: str = "file",
) -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="test",
        path_or_ref=path,
        title=title,
        excerpt=excerpt,
        reason="",
        confidence=confidence,
        est_tokens=est_tokens,
    )


class _StubCrossEncoder:
    """Stand-in for sentence-transformers.CrossEncoder.

    Returns a fixed raw score per (query, doc_text) pair via the supplied
    score_for callable. Mirrors the pattern in test_cross_encoder_rerank.
    """

    def __init__(self, score_for: Any) -> None:
        self._score_for = score_for
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, pairs: list[tuple[str, str]]):
        self.calls.append(list(pairs))
        return [self._score_for(query, doc) for query, doc in pairs]


def _install_stub(
    monkeypatch: pytest.MonkeyPatch, score_for: Any
) -> _StubCrossEncoder:
    """Drop a stub cross-encoder into the module-level cache."""
    import ranking.ranker as ranker_mod

    stub = _StubCrossEncoder(score_for)
    monkeypatch.setattr(ranker_mod, "_CROSS_ENCODER_MODEL", stub, raising=False)
    return stub


def _find_by_path(items: list[ContextItem], path: str) -> ContextItem:
    for item in items:
        if item.path_or_ref == path:
            return item
    raise AssertionError(f"path not found in output: {path}")


def test_source_prior_promotes_source_over_test_with_equal_cross_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At equal cross-encoder score, the source path beats the test path.

    blended = 0.5 * 0.5 + 0.5 * 0.5 = 0.5
    source: 0.5 * 1.15 = 0.575
    test:   0.5 * 0.85 = 0.425
    """
    _install_stub(monkeypatch, lambda _q, _d: 0.0)  # sigmoid(0) = 0.5

    ranker = ContextRanker(
        token_budget=10_000, use_rerank=True, use_embeddings=False
    )
    items = [
        _item(path="src/app/handlers/user.py", title="user_handler", confidence=0.5),
        _item(path="tests/handlers/test_user.py", title="test_user", confidence=0.5),
    ]
    out = ranker._apply_cross_encoder_rerank(items, "user handler")

    src = _find_by_path(out, "src/app/handlers/user.py")
    tst = _find_by_path(out, "tests/handlers/test_user.py")

    assert src.confidence == pytest.approx(0.575)
    assert tst.confidence == pytest.approx(0.425)
    assert src.confidence > tst.confidence


def test_source_prior_does_not_invert_huge_cross_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A massive cross-encoder gap still wins — the prior is a tiebreaker.

    Source raw -10 → sigmoid ~ 0.0; test raw +10 → sigmoid ~ 1.0. Both
    start at structural 0.5.
    test:   blended = 0.25 + 0.5 = 0.75; * 0.85 ~= 0.6375
    source: blended = 0.25 + 0.0 = 0.25; * 1.15 ~= 0.2875
    """
    src_path = "src/app/handlers/user.py"
    tst_path = "tests/handlers/test_user.py"

    def score(_query: str, doc: str) -> float:
        # The stub's "doc" is title + " " + excerpt[:cap]; we route by a
        # marker token in the excerpt so source/test pick up the right
        # raw score regardless of which order the rerank window iterates.
        return -10.0 if "SOURCE_DOC" in doc else 10.0

    _install_stub(monkeypatch, score)

    ranker = ContextRanker(
        token_budget=10_000, use_rerank=True, use_embeddings=False
    )
    items = [
        _item(
            path=src_path,
            title="user_handler",
            excerpt="SOURCE_DOC body",
            confidence=0.5,
        ),
        _item(
            path=tst_path,
            title="test_user",
            excerpt="TEST_DOC body",
            confidence=0.5,
        ),
    ]
    out = ranker._apply_cross_encoder_rerank(items, "user handler")

    src = _find_by_path(out, src_path)
    tst = _find_by_path(out, tst_path)

    assert tst.confidence == pytest.approx(0.6375, abs=1e-3)
    assert src.confidence == pytest.approx(0.2875, abs=1e-3)
    assert tst.confidence > src.confidence


def test_source_prior_clamps_to_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The prior multiplier can push past 0.95 — we clamp to the ceiling.

    structural=0.85, cross=sigmoid(10)~=1.0
    blended = 0.5 * 0.85 + 0.5 * 1.0 = 0.925
    * 1.15 = 1.064 → clamp to 0.95
    """
    _install_stub(monkeypatch, lambda _q, _d: 10.0)

    ranker = ContextRanker(
        token_budget=10_000, use_rerank=True, use_embeddings=False
    )
    items = [_item(path="src/main.py", title="main", confidence=0.85)]
    out = ranker._apply_cross_encoder_rerank(items, "main")

    final = _find_by_path(out, "src/main.py")
    assert final.confidence == pytest.approx(0.95)


@pytest.mark.parametrize(
    "path,expected_mult",
    [
        ("tests/foo.py", _RERANK_TEST_PRIOR_MULT),
        ("__tests__/foo.spec.ts", _RERANK_TEST_PRIOR_MULT),
        ("mocks/handlers.ts", _RERANK_TEST_PRIOR_MULT),
        ("scripts/run.sh", _RERANK_TEST_PRIOR_MULT),
        ("src/main.py", _RERANK_SOURCE_PRIOR_MULT),
        ("app/api/v1.py", _RERANK_SOURCE_PRIOR_MULT),
    ],
)
def test_test_path_classification_uses_existing_helper(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    expected_mult: float,
) -> None:
    """Each path picks up the same multiplier _is_test_or_script_path implies.

    With structural=0.5 and cross=sigmoid(0)=0.5, blended=0.5; final
    confidence = 0.5 * expected_mult.
    """
    _install_stub(monkeypatch, lambda _q, _d: 0.0)

    ranker = ContextRanker(
        token_budget=10_000, use_rerank=True, use_embeddings=False
    )
    items = [_item(path=path, title="sym", confidence=0.5)]
    out = ranker._apply_cross_encoder_rerank(items, "sym")

    final = _find_by_path(out, path)
    assert final.confidence == pytest.approx(0.5 * expected_mult)
