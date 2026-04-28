"""Tests for v4.4 Phase 3 — query-driven candidate widening + adaptive depth."""

from __future__ import annotations

from contracts.models import ContextItem
from core.orchestrator import (
    _classify_pack_depth,
    _matches_query_tokens,
    _tokens_for_query_match,
    _DEPTH_NARROW_TOP1,
    _DEPTH_NARROW_GAP,
    _DEPTH_STANDARD_TOP1,
)


# -----------------------------------------------------------------------
# Phase 3a: query-token tokenisation
# -----------------------------------------------------------------------

def test_tokens_for_query_match_splits_camelcase_and_snake_case() -> None:
    tokens = _tokens_for_query_match("Fix typo for client_secret in OAuth2 form docstrings")
    # CamelCase OAuth2 → "auth2" (the leading "o" is < min_len_3)
    assert "auth2" in tokens
    # snake_case client_secret → both halves
    assert "client" in tokens
    assert "secret" in tokens
    assert "form" in tokens
    assert "docstrings" in tokens


def test_tokens_for_query_match_drops_short_and_stop_words() -> None:
    tokens = _tokens_for_query_match("Fix the bug in main")
    # "fix", "the", "main" are stop tokens / short
    assert "fix" not in tokens
    assert "the" not in tokens
    assert "main" not in tokens
    # "bug" is 3 chars and not a stop word — kept
    assert "bug" in tokens


def test_tokens_for_query_match_empty_query_returns_empty() -> None:
    assert _tokens_for_query_match("") == set()


# -----------------------------------------------------------------------
# Phase 3a: filename / symbol-name matching
# -----------------------------------------------------------------------

def test_matches_query_tokens_hits_on_file_stem() -> None:
    tokens = {"oauth2"}
    assert _matches_query_tokens("oauth2", "any_function", tokens) is True


def test_matches_query_tokens_splits_camelcase_in_stem() -> None:
    """v4.4 Phase 3 tighten: stem-only matching (symbol-name match dropped
    after benchmarking showed it over-promoted noise)."""
    tokens = {"auth2"}
    # CamelCase OAuth2Form file stem → tokens include "auth2"
    assert _matches_query_tokens("OAuth2Form", "anything", tokens) is True


def test_matches_query_tokens_no_match_returns_false() -> None:
    tokens = {"oauth2"}
    assert _matches_query_tokens("logger", "log_message", tokens) is False


def test_matches_query_tokens_empty_tokens_returns_false() -> None:
    assert _matches_query_tokens("oauth2", "anything", set()) is False


# -----------------------------------------------------------------------
# Phase 3b: adaptive depth classification
# -----------------------------------------------------------------------

def _item(conf: float) -> ContextItem:
    return ContextItem(
        source_type="file",
        repo="test",
        path_or_ref=f"f_{conf}.py",
        title=f"item_{conf}",
        excerpt="x",
        reason="",
        confidence=conf,
        est_tokens=20,
    )


def test_depth_narrow_when_top1_high_and_gap_clear() -> None:
    items = [_item(0.85), _item(0.55), _item(0.45)]
    result = _classify_pack_depth(items)
    assert result["depth"] == "narrow"
    assert "0.85" in result["reason"]


def test_depth_standard_when_top1_moderate() -> None:
    # top1 = 0.65 above standard threshold but below narrow threshold
    items = [_item(0.65), _item(0.60), _item(0.55)]
    result = _classify_pack_depth(items)
    assert result["depth"] == "standard"


def test_depth_broad_when_top1_low() -> None:
    items = [_item(0.40), _item(0.35), _item(0.30)]
    result = _classify_pack_depth(items)
    assert result["depth"] == "broad"
    assert "exploratory" in result["reason"].lower()


def test_depth_narrow_demoted_when_gap_too_small() -> None:
    # Top1 high but gap to top2 below the 0.15 threshold
    items = [_item(0.80), _item(0.75), _item(0.50)]
    result = _classify_pack_depth(items)
    assert result["depth"] == "standard"


def test_depth_thresholds_match_design() -> None:
    """Lock in the narrow/standard thresholds so accidental tuning is caught."""
    assert _DEPTH_NARROW_TOP1 == 0.75
    assert _DEPTH_NARROW_GAP == 0.15
    assert _DEPTH_STANDARD_TOP1 == 0.55


def test_depth_handles_single_item_pack() -> None:
    items = [_item(0.90)]
    result = _classify_pack_depth(items)
    # Single high-conf item: c2 defaults to 0, gap is huge → narrow
    assert result["depth"] == "narrow"


def test_depth_handles_empty_pack() -> None:
    result = _classify_pack_depth([])
    assert result["depth"] == "broad"
    assert "empty" in result["reason"].lower()
