"""Tests for ``_dedup_stubs`` — symbol-stub-dedup (v3.2 P1).

The helper collapses near-duplicate ContextItems within a single file
when all three of (path_or_ref, title_prefix, excerpt) match. It does
NOT merge items with the same title but different excerpts (e.g. two
distinct ``class Config`` definitions in the same module).
"""

from __future__ import annotations

from contracts.models import ContextItem
from ranking import dedup_stubs
from ranking.ranker import ContextRanker, _dedup_stubs


def _item(
    *,
    path: str = "fastapi/security/oauth2.py",
    title: str = "__init__",
    excerpt: str = "def __init__(",
    confidence: float = 0.5,
    source_type: str = "file",
    est_tokens: int = 50,
) -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="fastapi",
        path_or_ref=path,
        title=title,
        excerpt=excerpt,
        reason="symbol",
        confidence=confidence,
        est_tokens=est_tokens,
    )


# -----------------------------------------------------------------------
# Positive case: identical stubs collapse
# -----------------------------------------------------------------------

def test_identical_stubs_collapse_to_one_representative() -> None:
    """5 items with identical path + title + excerpt -> 1 rep with dup=4."""
    items = [_item() for _ in range(5)]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 4
    assert out[0].duplicates_hidden == 4


def test_public_alias_matches_private() -> None:
    """The public ``dedup_stubs`` name exports the same callable."""
    assert dedup_stubs is _dedup_stubs


def test_title_suffix_variation_still_collapses() -> None:
    """``def __init__(self, x)`` and ``def __init__(self)`` share the prefix
    before ``(`` — with an identical excerpt they must collapse."""
    items = [
        _item(title="__init__(self)", excerpt="def __init__("),
        _item(title="__init__(self, x)", excerpt="def __init__("),
        _item(title="__init__(self, x, y)", excerpt="def __init__("),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 2
    assert out[0].duplicates_hidden == 2


def test_highest_confidence_kept_as_representative() -> None:
    """Caller pre-sorts by confidence descending; dedup keeps first (highest)."""
    items = [
        _item(confidence=0.9, title="__init__"),
        _item(confidence=0.5, title="__init__"),
        _item(confidence=0.3, title="__init__"),
    ]
    out, _ = _dedup_stubs(items)
    assert len(out) == 1
    assert out[0].confidence == 0.9
    assert out[0].duplicates_hidden == 2


# -----------------------------------------------------------------------
# Negative cases: must NOT merge
# -----------------------------------------------------------------------

def test_same_title_different_excerpts_not_merged() -> None:
    """Two distinct ``class Config`` items — same title, different bodies.

    Threshold from the outcome: "items with different excerpts but the
    same title (e.g. two distinct classes both named Config) are NOT
    merged".
    """
    items = [
        _item(title="Config", excerpt="class Config:\n    debug = True"),
        _item(title="Config", excerpt="class Config:\n    timeout = 30"),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 2
    assert dropped == 0
    assert all(i.duplicates_hidden == 0 for i in out)


def test_same_excerpt_different_paths_not_merged() -> None:
    """Same stub excerpt across DIFFERENT files stays separate — we only
    dedup within a single file."""
    items = [
        _item(path="a.py", title="__init__", excerpt="def __init__("),
        _item(path="b.py", title="__init__", excerpt="def __init__("),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 2
    assert dropped == 0


def test_empty_input_no_crash() -> None:
    assert _dedup_stubs([]) == ([], 0)


def test_single_item_unchanged() -> None:
    items = [_item()]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 0
    assert out[0].duplicates_hidden == 0


def test_path_normalisation_matches_variants() -> None:
    """Leading ``./`` and case differences in the path are normalised."""
    items = [
        _item(path="./fastapi/security/oauth2.py"),
        _item(path="fastapi/security/oauth2.py"),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 1


def test_mixed_duplicates_and_uniques() -> None:
    """Three duplicate __init__ + one distinct class Foo -> 2 items out."""
    items = [
        _item(title="__init__", excerpt="def __init__("),
        _item(title="__init__", excerpt="def __init__("),
        _item(title="__init__", excerpt="def __init__("),
        _item(title="Foo", excerpt="class Foo:"),
    ]
    out, dropped = _dedup_stubs(items)
    assert len(out) == 2
    assert dropped == 2
    reps = {i.title: i for i in out}
    assert reps["__init__"].duplicates_hidden == 2
    assert reps["Foo"].duplicates_hidden == 0


# -----------------------------------------------------------------------
# Integration: the ranker calls _dedup_stubs before _enforce_budget
# -----------------------------------------------------------------------

def test_ranker_applies_stub_dedup_inside_rank() -> None:
    """End-to-end: 5 identical stubs fed to ``rank()`` come out as 1
    with ``duplicates_hidden`` >= 4."""
    items = [
        _item(confidence=0.9 - i * 0.01)
        for i in range(5)
    ]
    ranker = ContextRanker(token_budget=100_000)
    out = ranker.rank(items, "OAuth2 form", "review")
    # All 5 were identical → collapsed into 1.
    assert len(out) == 1
    assert out[0].duplicates_hidden == 4
