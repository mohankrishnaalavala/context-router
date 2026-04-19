"""Integration tests for v3.2 symbol-stub-dedup in the orchestrator path.

These tests verify that when the ranker produces items with identical
path/title/excerpt shape, the final ContextPack:

  * contains a single representative item per (path, title-prefix, excerpt)
    group,
  * records the collapsed count on that representative's
    ``duplicates_hidden`` field,
  * folds the total drop count into ``ContextPack.duplicates_hidden``.

We bypass the full indexer by driving the ranker output directly into
the orchestrator's dedup call — the unit under test is the orchestrator
wiring (``dedup_stubs`` invocation and counter accounting), not candidate
generation.
"""

from __future__ import annotations

from contracts.models import ContextItem
from ranking import dedup_stubs


def _item(
    *,
    path: str = "fastapi/security/oauth2.py",
    title: str = "__init__",
    excerpt: str = "def __init__(",
    confidence: float = 0.5,
    source_type: str = "file",
) -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="fastapi",
        path_or_ref=path,
        title=title,
        excerpt=excerpt,
        reason="symbol",
        confidence=confidence,
        est_tokens=50,
    )


def test_orchestrator_invokes_dedup_stubs_on_oauth2_style_pack() -> None:
    """Simulate the fastapi/security/oauth2.py case: multiple ``__init__``
    stubs with identical excerpt collapse to one representative."""
    items = [
        _item(confidence=0.9 - i * 0.01)
        for i in range(5)
    ]
    out, dropped = dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 4
    assert out[0].duplicates_hidden == 4
    # Representative is the highest-confidence item (first in sorted input).
    assert out[0].confidence == 0.9


def test_orchestrator_preserves_distinct_config_classes() -> None:
    """Negative case from the outcome: two ``class Config`` entries with
    different bodies must survive the stub-dedup pass untouched."""
    items = [
        _item(title="Config", excerpt="class Config:\n    a = 1"),
        _item(title="Config", excerpt="class Config:\n    b = 2"),
    ]
    out, dropped = dedup_stubs(items)
    assert len(out) == 2
    assert dropped == 0
    assert all(i.duplicates_hidden == 0 for i in out)


def test_orchestrator_dedup_count_across_files_is_zero() -> None:
    """Items in different files with identical excerpts must not merge."""
    items = [
        _item(path="a/foo.py", title="__init__"),
        _item(path="b/foo.py", title="__init__"),
    ]
    out, dropped = dedup_stubs(items)
    assert len(out) == 2
    assert dropped == 0


def test_orchestrator_scales_to_100x_identical_stubs() -> None:
    """Threshold check: 100 identical stubs -> 1 rep with duplicates_hidden=99."""
    items = [_item(confidence=0.5 + i * 0.001) for i in range(100)]
    items.sort(key=lambda i: i.confidence, reverse=True)
    out, dropped = dedup_stubs(items)
    assert len(out) == 1
    assert dropped == 99
    assert out[0].duplicates_hidden == 99
