"""Tests for B3: _enrich_with_symbol_bodies."""
from pathlib import Path
from unittest.mock import MagicMock

from contracts.models import ContextItem


def _make_item(path: str, title: str, repo: str = "default") -> ContextItem:
    return ContextItem(
        source_type="file",
        repo=repo,
        path_or_ref=path,
        title=title,
        excerpt="def foo():",
        reason="Referenced in codebase",
        confidence=0.8,
        est_tokens=50,
    )


def test_enrich_populates_body_from_line_range(tmp_path: Path):
    """_enrich_with_symbol_bodies reads the line range and sets symbol_body."""
    from core.orchestrator import Orchestrator

    # Create a real temp file with known content
    src = tmp_path / "mymodule.py"
    src.write_text("line1\nline2\nline3\nline4\nline5\n")

    item = _make_item(str(src), "myFunc (mymodule.py)")

    # Mock sym_repo that returns lines 2-4 for this item
    sym_repo = MagicMock()
    sym_repo.fetch_symbol_lines_batch.return_value = {
        ("default", str(src), "myFunc"): (2, 4)
    }

    orch = Orchestrator.__new__(Orchestrator)
    orch._root = tmp_path

    result = orch._enrich_with_symbol_bodies([item], sym_repo)

    assert len(result) == 1
    assert result[0].symbol_lines == (2, 4)
    assert result[0].symbol_body == "line2\nline3\nline4"


def test_enrich_skips_memory_items(tmp_path: Path):
    """Memory and decision items are never enriched."""
    from core.orchestrator import Orchestrator

    mem_item = ContextItem(
        source_type="memory",
        repo="default",
        path_or_ref="",
        title="some observation",
        excerpt="...",
        reason="past session",
        confidence=0.7,
        est_tokens=30,
    )
    sym_repo = MagicMock()

    orch = Orchestrator.__new__(Orchestrator)
    orch._root = tmp_path

    result = orch._enrich_with_symbol_bodies([mem_item], sym_repo)

    sym_repo.fetch_symbol_lines_batch.assert_not_called()
    assert result[0].symbol_body is None


def test_enrich_handles_missing_symbol_gracefully(tmp_path: Path):
    """Items with no matching DB entry stay unchanged (no crash)."""
    from core.orchestrator import Orchestrator

    src = tmp_path / "other.py"
    src.write_text("content\n")
    item = _make_item(str(src), "missingFunc (other.py)")

    sym_repo = MagicMock()
    sym_repo.fetch_symbol_lines_batch.return_value = {}  # not found

    orch = Orchestrator.__new__(Orchestrator)
    orch._root = tmp_path

    result = orch._enrich_with_symbol_bodies([item], sym_repo)

    assert result[0].symbol_body is None
    assert result[0].symbol_lines is None


# -----------------------------------------------------------------------
# v4.4 Phase 5: top-1-only symbol-body inlining
# -----------------------------------------------------------------------

def test_enrich_inlines_only_top_1_by_default(tmp_path: Path):
    """Phase 5: only the highest-ranked code item gets symbol_body inlined.

    Lower-ranked items still get symbol_lines (for cheap follow-up reads)
    but skip the body bytes — saves ~70% of JSON serialisation cost on a
    typical 5-item pack.
    """
    from core.orchestrator import Orchestrator

    src1 = tmp_path / "alpha.py"
    src1.write_text("a1\na2\na3\na4\na5\n")
    src2 = tmp_path / "beta.py"
    src2.write_text("b1\nb2\nb3\nb4\nb5\n")
    src3 = tmp_path / "gamma.py"
    src3.write_text("c1\nc2\nc3\nc4\nc5\n")

    items = [
        _make_item(str(src1), "alpha (alpha.py)"),
        _make_item(str(src2), "beta (beta.py)"),
        _make_item(str(src3), "gamma (gamma.py)"),
    ]

    sym_repo = MagicMock()
    sym_repo.fetch_symbol_lines_batch.return_value = {
        ("default", str(src1), "alpha"): (1, 3),
        ("default", str(src2), "beta"): (1, 3),
        ("default", str(src3), "gamma"): (1, 3),
    }

    orch = Orchestrator.__new__(Orchestrator)
    orch._root = tmp_path

    result = orch._enrich_with_symbol_bodies(items, sym_repo)

    assert len(result) == 3
    # Top item: full body inlined
    assert result[0].symbol_body == "a1\na2\na3"
    assert result[0].symbol_lines == (1, 3)
    # Lower-ranked items: only line range, no body bytes
    assert result[1].symbol_body is None
    assert result[1].symbol_lines == (1, 3)
    assert result[2].symbol_body is None
    assert result[2].symbol_lines == (1, 3)


def test_enrich_inline_top_only_false_restores_legacy_behaviour(tmp_path: Path):
    """Pass inline_top_only=False to inline every item (v4.4 B3 default)."""
    from core.orchestrator import Orchestrator

    src1 = tmp_path / "x.py"
    src1.write_text("x1\nx2\n")
    src2 = tmp_path / "y.py"
    src2.write_text("y1\ny2\n")

    items = [
        _make_item(str(src1), "xfn (x.py)"),
        _make_item(str(src2), "yfn (y.py)"),
    ]

    sym_repo = MagicMock()
    sym_repo.fetch_symbol_lines_batch.return_value = {
        ("default", str(src1), "xfn"): (1, 2),
        ("default", str(src2), "yfn"): (1, 2),
    }

    orch = Orchestrator.__new__(Orchestrator)
    orch._root = tmp_path

    result = orch._enrich_with_symbol_bodies(items, sym_repo, inline_top_only=False)

    assert result[0].symbol_body == "x1\nx2"
    assert result[1].symbol_body == "y1\ny2"
