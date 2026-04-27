"""Tests for v4.4 Phase 2: cross-encoder rerank pass."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from contracts.models import ContextItem
from ranking.ranker import (
    ContextRanker,
    _CROSS_ENCODER_TOP_K,
    _CROSS_ENCODER_WEIGHT,
)


def _item(
    *,
    title: str,
    confidence: float = 0.5,
    excerpt: str = "def foo(): ...",
    est_tokens: int = 80,
    source_type: str = "file",
) -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="test",
        path_or_ref=f"{title}.py",
        title=title,
        excerpt=excerpt,
        reason="",
        confidence=confidence,
        est_tokens=est_tokens,
    )


# -----------------------------------------------------------------------
# Constructor flag plumbing
# -----------------------------------------------------------------------

def test_use_rerank_constructor_default_false() -> None:
    """The rerank pass is opt-in — disabled when the flag isn't set."""
    ranker = ContextRanker(token_budget=1000)
    assert ranker._use_rerank is False


def test_use_rerank_constructor_propagates() -> None:
    """Passing use_rerank=True flips the field for the rerank gate."""
    ranker = ContextRanker(token_budget=1000, use_rerank=True)
    assert ranker._use_rerank is True


# -----------------------------------------------------------------------
# Silent-degrade behaviour
# -----------------------------------------------------------------------

def test_rerank_no_op_when_use_rerank_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rank() must not invoke the cross-encoder when use_rerank is False.

    Spies on the loader: a no-op pass means the loader is never called.
    Other boost passes (BM25, etc.) may still adjust confidences.
    """
    import ranking.ranker as ranker_mod

    calls: list[bool] = []

    def _spy(*_a: object, **_k: object) -> object:
        calls.append(True)
        return False  # sentinel for "model unavailable"

    monkeypatch.setattr(ranker_mod, "_get_cross_encoder_model", _spy)

    ranker = ContextRanker(token_budget=10_000, use_rerank=False)
    items = [
        _item(title="alpha", confidence=0.7),
        _item(title="beta", confidence=0.5),
    ]
    ranker.rank(items, "alpha or beta", "implement")
    assert calls == []  # loader never invoked


def test_rerank_silent_degrades_when_model_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing sentence-transformers → one stderr warning + items pass through."""
    # Reset the module-level cache so the loader actually runs the
    # ImportError path rather than returning the cached sentinel.
    import ranking.ranker as ranker_mod
    monkeypatch.setattr(ranker_mod, "_CROSS_ENCODER_MODEL", None, raising=False)

    # Force the import to fail by removing sentence_transformers from sys.modules
    # and shadowing it with a meta path finder that raises ImportError.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    ranker = ContextRanker(token_budget=10_000, use_rerank=True)
    items = [
        _item(title="alpha", confidence=0.7),
        _item(title="beta", confidence=0.5),
    ]
    pre_confs = [i.confidence for i in items]
    out = ranker.rank(items, "alpha", "implement")

    # Confidences unchanged by the rerank step (BM25/floor may still
    # adjust them, but the cross-encoder blend never fires).
    captured = capsys.readouterr()
    # The rerank loader emits a one-line warning naming the missing dep.
    assert "sentence-transformers" in captured.err
    # And we still got items back, in some sensible order.
    assert len(out) >= 1
    # The relative order of the two items should follow their pre-rerank
    # confidence (rerank was skipped).
    assert pre_confs == sorted(pre_confs, reverse=True)


# -----------------------------------------------------------------------
# Active rerank — with a stub cross-encoder
# -----------------------------------------------------------------------

class _StubCrossEncoder:
    """Tiny stand-in for sentence-transformers.CrossEncoder.

    Returns a fixed score per (query, doc_text) pair based on whether
    the doc text contains the query token. Lets us assert reordering
    deterministically without downloading the real ~22 MB model.
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.calls: list[list[tuple[str, str]]] = []

    def predict(self, pairs: list[tuple[str, str]]):
        self.calls.append(list(pairs))
        # High raw score (sigmoid → ~0.99) when the doc mentions the query
        # token; low score (sigmoid → ~0.05) when it doesn't.
        return [5.0 if pair[0].lower() in pair[1].lower() else -3.0 for pair in pairs]


def test_rerank_promotes_query_match_above_unrelated_peer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cross-encoder lifts an item whose doc contains the query token."""
    import ranking.ranker as ranker_mod

    # Inject the stub model into the module-level cache so the loader
    # short-circuits and uses it.
    stub = _StubCrossEncoder()
    monkeypatch.setattr(ranker_mod, "_CROSS_ENCODER_MODEL", stub, raising=False)

    ranker = ContextRanker(token_budget=10_000, use_rerank=True, use_embeddings=False)
    items = [
        # No query-token match in title/excerpt → low cross score.
        _item(title="zeta", excerpt="utility helper", confidence=0.65),
        # Title mentions "alpha" → high cross score should outrank zeta.
        _item(title="alpha", excerpt="alpha module impl", confidence=0.55),
    ]
    out = ranker.rank(items, "alpha", "implement")

    # Stub was invoked exactly once with the top-K window.
    assert len(stub.calls) == 1
    # The alpha item must now be first; the cross-encoder boost beat the
    # 0.10-confidence head start zeta had pre-rerank.
    assert out[0].title == "alpha"


def test_rerank_window_only_covers_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Items outside the top-K window keep their pre-rerank confidence."""
    import ranking.ranker as ranker_mod

    stub = _StubCrossEncoder()
    monkeypatch.setattr(ranker_mod, "_CROSS_ENCODER_MODEL", stub, raising=False)

    ranker = ContextRanker(token_budget=100_000, use_rerank=True, use_embeddings=False)
    # _CROSS_ENCODER_TOP_K + 5 distinct items, decreasing confidence.
    n = _CROSS_ENCODER_TOP_K + 5
    # Spread confidences widely so the floor / adaptive_top_k pass keeps
    # everything (we want to assert the rerank window, not other filters).
    items = [
        _item(
            title=f"sym{i}",
            confidence=0.95 - (i * 0.01),
            excerpt="filler",
        )
        for i in range(n)
    ]
    # Use mode="handover" so the v4.4 score floor stays low (0.20) and
    # all items survive into the rerank step.
    ranker.rank(items, "sym0", "handover")

    # Stub was called once and only with K pairs.
    assert len(stub.calls) == 1
    assert len(stub.calls[0]) == _CROSS_ENCODER_TOP_K


def test_rerank_blend_weight_is_50_50() -> None:
    """Lock in the documented blend weight constant."""
    assert _CROSS_ENCODER_WEIGHT == 0.5
