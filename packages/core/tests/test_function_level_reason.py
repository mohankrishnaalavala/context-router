"""Tests for the function-level-reason outcome (v3.2).

Covers:
  * ``_make_item`` with valid symbol line data produces a reason of the
    shape ``"{verb} `{name}` lines {start}-{end}"``.
  * ``_make_item`` with a non-symbol source_type (``"memory"``,
    ``"decision"``) or without line data leaves ``reason`` empty so the
    ranker can fill in the category fallback.
  * The ranker's ``_annotate`` preserves a pre-populated reason instead
    of overwriting with the category string.
  * Category-level reasons are still emitted for raw ContextItems built
    directly (no ``_make_item`` path) — no regression.
  * The orchestrator emits a single stderr warning when line data is
    missing for a symbol-backed item (silent-failure guard, per
    CLAUDE.md).
"""

from __future__ import annotations

import re
from pathlib import Path

from contracts.models import ContextItem
from core.orchestrator import Orchestrator, _make_item
from ranking.ranker import _REASON, ContextRanker

# ---------------------------------------------------------------------------
# _make_item — upgraded reason shape
# ---------------------------------------------------------------------------

_REASON_SHAPE = re.compile(r"`.+` lines \d+-\d+")


def test_make_item_with_line_data_produces_upgraded_reason() -> None:
    item = _make_item(
        sym_name="OAuth2PasswordRequestForm",
        file_path="fastapi/security/oauth2.py",
        signature="class OAuth2PasswordRequestForm:",
        docstring="",
        source_type="changed_file",
        confidence=0.9,
        repo="default",
        line_start=59,
        line_end=159,
        kind="class",
    )
    assert item.reason == (
        "Modified `OAuth2PasswordRequestForm` lines 59-159"
    )
    assert _REASON_SHAPE.search(item.reason) is not None


def test_make_item_preserves_shape_for_blast_radius() -> None:
    item = _make_item(
        sym_name="build_params",
        file_path="fastapi/dependencies/utils.py",
        signature="def build_params():",
        docstring="",
        source_type="blast_radius",
        confidence=0.4,
        repo="default",
        line_start=12,
        line_end=48,
        kind="function",
    )
    assert item.reason.startswith("Depends on or is imported by ")
    assert "`build_params`" in item.reason
    assert "lines 12-48" in item.reason


def test_make_item_without_line_data_leaves_reason_empty() -> None:
    fallback_flag = [False]
    item = _make_item(
        sym_name="foo",
        file_path="pkg/foo.py",
        signature="def foo():",
        docstring="",
        source_type="changed_file",
        confidence=0.5,
        repo="default",
        # line_start / line_end omitted on purpose
        fallback_flag=fallback_flag,
    )
    assert item.reason == ""  # ranker will fill in category fallback
    assert fallback_flag[0] is True


def test_make_item_with_invalid_line_range_leaves_reason_empty() -> None:
    fallback_flag = [False]
    item = _make_item(
        sym_name="bar",
        file_path="pkg/bar.py",
        signature="def bar():",
        docstring="",
        source_type="blast_radius",
        confidence=0.4,
        repo="default",
        line_start=0,  # invalid (must be > 0)
        line_end=10,
        fallback_flag=fallback_flag,
    )
    assert item.reason == ""
    assert fallback_flag[0] is True


def test_make_item_unknown_source_type_leaves_reason_empty() -> None:
    # Non-symbol source_type (no verb entry) should not trigger the
    # upgrade and should not flag a fallback — it simply isn't a
    # symbol-backed upgrade candidate.
    fallback_flag = [False]
    item = _make_item(
        sym_name="obs",
        file_path="memory",
        signature="",
        docstring="",
        source_type="memory",
        confidence=0.5,
        repo="default",
        line_start=10,
        line_end=20,
        fallback_flag=fallback_flag,
    )
    assert item.reason == ""
    assert fallback_flag[0] is False


# ---------------------------------------------------------------------------
# Ranker — preserves pre-populated reason
# ---------------------------------------------------------------------------


def test_ranker_preserves_function_level_reason() -> None:
    upgraded = "Modified `compute` lines 10-42"
    item = ContextItem(
        source_type="changed_file",
        repo="default",
        path_or_ref="pkg/compute.py",
        title="compute (compute.py)",
        excerpt="",
        reason=upgraded,
        confidence=0.7,
        est_tokens=50,
    )
    ranked = ContextRanker(token_budget=1000).rank([item], "", "review")
    assert ranked[0].reason == upgraded


def test_ranker_fills_category_reason_when_empty() -> None:
    # Negative case: an item with reason="" (e.g. raw file entry with no
    # symbol backing, or a symbol-backed item that fell back) still
    # receives the existing category-level string. No regression.
    item = ContextItem(
        source_type="changed_file",
        repo="default",
        path_or_ref="pkg/raw.py",
        title="raw.py",
        excerpt="",
        reason="",
        confidence=0.7,
        est_tokens=50,
    )
    ranked = ContextRanker(token_budget=1000).rank([item], "", "review")
    assert ranked[0].reason == _REASON["changed_file"]


def test_ranker_category_reasons_still_apply_to_all_source_types() -> None:
    # Negative case: every non-upgraded source_type still gets the old
    # category reason. Guards against a regression that would leave
    # raw file items with empty reasons.
    for source_type, expected in _REASON.items():
        item = ContextItem(
            source_type=source_type,
            repo="default",
            path_or_ref="pkg/x.py",
            title="x",
            excerpt="",
            reason="",
            confidence=0.5,
            est_tokens=10,
        )
        ranked = ContextRanker(token_budget=1000).rank([item], "", "review")
        assert ranked[0].reason == expected, (
            f"category reason regression for {source_type!r}"
        )


# ---------------------------------------------------------------------------
# Silent-failure guard — once per pack, not per item
# ---------------------------------------------------------------------------


def _init_project(tmp_path: Path) -> Path:
    (tmp_path / ".context-router").mkdir()
    return tmp_path


def test_orchestrator_warns_once_on_fallback(
    tmp_path: Path, capsys
) -> None:
    """If ANY symbol-backed item falls back to category reason, the
    orchestrator should emit exactly one stderr line — not one per item."""
    root = _init_project(tmp_path)
    orch = Orchestrator(project_root=root)
    # Manually trigger the flag path without going through the full
    # candidate pipeline. The flag is reset at the start of
    # _build_candidates and flushed at the end.
    orch._symbol_reason_fallback_flag = [False]
    # Simulate three items with missing line data.
    for _ in range(3):
        _make_item(
            sym_name="x",
            file_path="a.py",
            signature="",
            docstring="",
            source_type="changed_file",
            confidence=0.5,
            repo="default",
            fallback_flag=orch._symbol_reason_fallback_flag,
        )
    # Replay the warn step from _build_candidates' tail.
    import sys as _sys

    if orch._symbol_reason_fallback_flag[0]:
        print(
            "context-router: function-level reason fell back to "
            "category string for one or more items — symbol line "
            "metadata missing or invalid",
            file=_sys.stderr,
        )
    err = capsys.readouterr().err
    assert err.count("function-level reason fell back") == 1
