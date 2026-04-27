"""Tests for v4.4 precision-first score floor + restricted per-type guarantee."""

from __future__ import annotations

from contracts.models import ContextItem
from ranking.ranker import (
    ContextRanker,
    _GUARANTEED_SOURCE_TYPES,
    _MODE_SCORE_FLOORS_ABS,
    _PER_TASK_FLOOR_MODES,
    _SCORE_FLOOR_ABS_PER_TASK,
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
# Score floor — per-task modes (review / implement / minimal)
# -----------------------------------------------------------------------

def test_implement_floor_drops_low_conf_file_items() -> None:
    """conf-0.20 'file' items get dropped before budget enforcement in implement.

    Uses an empty query so BM25 boost is bypassed and structural confidences
    are preserved verbatim — isolates the floor's behavior from BM25 effects.
    Item ``ct`` is set above both the floor (0.4675=0.85*0.55) and the
    existing adaptive_top_k cutoff (0.51=0.85*0.6) so it must survive both.
    """
    items = [
        _item(confidence=0.85, source_type="entrypoint", title="ep"),
        _item(confidence=0.60, source_type="contract", title="ct"),
        _item(confidence=0.20, source_type="file", title="noise1"),
        _item(confidence=0.20, source_type="file", title="noise2"),
    ]
    result = ContextRanker(token_budget=10_000).rank(items, "", "implement")
    titles = {i.title for i in result}
    assert "ep" in titles
    assert "ct" in titles
    assert "noise1" not in titles  # below floor (0.4675 = 0.85 * 0.55)
    assert "noise2" not in titles


def test_review_floor_uses_relative_55pct_when_top_is_high() -> None:
    """When top1 is high (e.g. 0.95), floor = top1 * 0.55, not the abs 0.45.

    Sets ``br`` above both the floor (0.5225=0.95*0.55) and the adaptive
    top-k cutoff (0.57=0.95*0.6) so it survives both filters.
    """
    items = [
        _item(confidence=0.95, source_type="changed_file", title="cf"),
        _item(confidence=0.60, source_type="blast_radius", title="br"),
        _item(confidence=0.40, source_type="file", title="below"),
    ]
    result = ContextRanker(token_budget=10_000).rank(items, "", "review")
    titles = {i.title for i in result}
    assert "cf" in titles
    assert "br" in titles
    assert "below" not in titles


def test_per_task_floor_always_keeps_top_item() -> None:
    """Even when all items are below the abs floor, top-1 survives."""
    items = [
        _item(confidence=0.30, source_type="file", title="onlyitem"),
    ]
    result = ContextRanker(token_budget=10_000).rank(items, "", "implement")
    assert len(result) == 1
    assert result[0].title == "onlyitem"


def test_minimal_uses_per_task_floor() -> None:
    """Minimal mode shares the per-task floor (max(top1*0.55, 0.45))."""
    assert "minimal" in _PER_TASK_FLOOR_MODES
    items = [
        _item(confidence=0.80, source_type="entrypoint", title="ep"),
        _item(confidence=0.20, source_type="file", title="noise"),
    ]
    result = ContextRanker(token_budget=800).rank(items, "", "minimal")
    titles = {i.title for i in result}
    assert "ep" in titles
    assert "noise" not in titles


# -----------------------------------------------------------------------
# Score floor — debug / handover modes (absolute)
# -----------------------------------------------------------------------

def test_debug_floor_is_lower_than_per_task() -> None:
    """Debug uses a 0.30 absolute floor — keeps mid-conf call-chain items."""
    assert _MODE_SCORE_FLOORS_ABS["debug"] == 0.30
    items = [
        _item(confidence=0.45, source_type="changed_file", title="cf"),
        _item(confidence=0.31, source_type="call_chain", title="cc1"),  # above 0.30
        _item(confidence=0.20, source_type="file", title="noise"),  # below 0.30
    ]
    result = ContextRanker(token_budget=10_000).rank(items, "", "debug")
    titles = {i.title for i in result}
    assert "cf" in titles
    assert "cc1" in titles
    assert "noise" not in titles


def test_handover_floor_is_widest() -> None:
    """Handover uses 0.20 floor — widest of all modes."""
    assert _MODE_SCORE_FLOORS_ABS["handover"] == 0.20
    items = [
        _item(confidence=0.85, source_type="changed_file", title="cf"),
        _item(confidence=0.21, source_type="file", title="kept"),
        _item(confidence=0.15, source_type="file", title="dropped"),
    ]
    result = ContextRanker(token_budget=10_000).rank(items, "", "handover")
    titles = {i.title for i in result}
    assert "cf" in titles
    assert "kept" in titles
    assert "dropped" not in titles


# -----------------------------------------------------------------------
# Memory items exempt from score floor
# -----------------------------------------------------------------------

def test_memory_items_exempt_from_score_floor() -> None:
    """Memory/decision items have their own freshness scoring; floor skips them.

    Uses handover mode so the existing adaptive_top_k pass (review/implement
    only) does not also drop the low-conf memory items — the assertion is
    about the score_floor specifically exempting memory types.
    """
    items = [
        _item(confidence=0.80, source_type="changed_file", title="cf"),
        _item(confidence=0.25, source_type="memory", title="mem"),
        _item(confidence=0.25, source_type="decision", title="dec"),
    ]
    result = ContextRanker(token_budget=10_000).rank(items, "", "handover")
    titles = {i.title for i in result}
    assert "cf" in titles
    assert "mem" in titles
    assert "dec" in titles


# -----------------------------------------------------------------------
# Restricted per-source-type guarantee — _enforce_budget behaviour
# -----------------------------------------------------------------------

def test_file_type_no_longer_guaranteed_when_over_budget() -> None:
    """A 'file' item that doesn't fit the budget is dropped (no guarantee)."""
    assert "file" not in _GUARANTEED_SOURCE_TYPES
    items = [
        _item(confidence=0.90, source_type="entrypoint", est_tokens=80, title="ep"),
        _item(confidence=0.55, source_type="file", est_tokens=200, title="bigfile"),
    ]
    result = ContextRanker(token_budget=100).rank(items, "", "implement")
    titles = {i.title for i in result}
    assert "ep" in titles
    # bigfile is conf 0.55 (>= floor 0.495=0.9*0.55), 200 tokens, doesn't fit;
    # without the file-type guarantee it gets dropped.
    assert "bigfile" not in titles


def test_high_signal_type_still_gets_guarantee() -> None:
    """changed_file type retains the guarantee even when over budget."""
    assert "changed_file" in _GUARANTEED_SOURCE_TYPES
    items = [
        _item(confidence=0.90, source_type="entrypoint", est_tokens=80, title="ep"),
        _item(confidence=0.85, source_type="changed_file", est_tokens=200, title="cf"),
    ]
    result = ContextRanker(token_budget=100).rank(items, "", "review")
    titles = {i.title for i in result}
    assert "ep" in titles
    assert "cf" in titles  # guaranteed despite exceeding budget


def test_guaranteed_set_covers_high_signal_types() -> None:
    """Spot check the high-signal guarantee set matches the design."""
    expected = {
        "entrypoint",
        "changed_file",
        "runtime_signal",
        "contract",
        "extension_point",
        "failing_test",
        "past_debug",
        "blast_radius",
        "impacted_test",
    }
    assert expected <= _GUARANTEED_SOURCE_TYPES
    # Catch-all "file" type explicitly NOT guaranteed
    assert "file" not in _GUARANTEED_SOURCE_TYPES


# -----------------------------------------------------------------------
# Mode-aware budget defaults from config
# -----------------------------------------------------------------------

def test_score_floor_constants_match_design() -> None:
    """Lock in the floor constants per the v4.4 design."""
    assert _SCORE_FLOOR_ABS_PER_TASK == 0.45
    assert _MODE_SCORE_FLOORS_ABS["debug"] == 0.30
    assert _MODE_SCORE_FLOORS_ABS["handover"] == 0.20
