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
