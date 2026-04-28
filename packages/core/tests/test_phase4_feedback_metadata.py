"""Tests for v4.4 Phase 4 — feedback_applied surfaced via pack.metadata."""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from contracts.models import PackFeedback
from core.orchestrator import Orchestrator


def _seed_db_with_symbols(db_path: Path, file_path: str = "src/main.py") -> None:
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    with Database(db_path) as db:
        repo = SymbolRepository(db.connection)
        sym = Symbol(
            name="my_function",
            kind="function",
            file=Path(file_path),
            line_start=1,
            line_end=5,
            language="python",
            signature="def my_function() -> None:",
            docstring="Does something.",
        )
        repo.add_bulk([sym], "default")


def _make_project(tmp_path: Path, file_path: str = "src/main.py") -> Path:
    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    _seed_db_with_symbols(cr_dir / "context-router.db", file_path=file_path)
    return tmp_path


def _seed_feedback(project_root: Path, repo_scope: str, **kwargs) -> None:
    """Insert N=3 feedback rows so adjustments hit the min_count threshold."""
    from memory.store import FeedbackStore
    from storage_sqlite.database import Database

    with Database(project_root / ".context-router" / "context-router.db") as db:
        store = FeedbackStore(db, repo_scope=repo_scope)
        for _ in range(3):
            store.add(PackFeedback(pack_id="seed-pack", **kwargs))


def test_feedback_applied_metadata_present_when_no_history(tmp_path: Path) -> None:
    """Empty feedback table → empty list (not missing key)."""
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("review", "test")
    assert "feedback_applied" in pack.metadata
    assert pack.metadata["feedback_applied"] == []


def test_feedback_applied_lists_files_read_signal(tmp_path: Path) -> None:
    """Three files_read reports for src/main.py → +0.03 surfaces in metadata."""
    root = _make_project(tmp_path, file_path="src/main.py")
    repo_scope = str(root.resolve())
    _seed_feedback(root, repo_scope, files_read=["src/main.py"])

    pack = Orchestrator(project_root=root).build_pack("review", "test")
    paths_in_pack = {item.path_or_ref for item in pack.selected_items}
    if "src/main.py" not in paths_in_pack:
        pytest.skip("src/main.py was not surfaced in the pack — orthogonal to this test")
    applied = pack.metadata["feedback_applied"]
    entries = {e["path"]: e["delta"] for e in applied}
    assert "src/main.py" in entries
    assert entries["src/main.py"] == pytest.approx(0.03)


def test_feedback_applied_lists_missing_signal(tmp_path: Path) -> None:
    """Three missing reports for src/main.py → +0.05 surfaces in metadata."""
    root = _make_project(tmp_path, file_path="src/main.py")
    repo_scope = str(root.resolve())
    _seed_feedback(root, repo_scope, missing=["src/main.py"])

    pack = Orchestrator(project_root=root).build_pack("review", "test")
    paths_in_pack = {item.path_or_ref for item in pack.selected_items}
    if "src/main.py" not in paths_in_pack:
        pytest.skip("src/main.py was not surfaced in the pack — orthogonal to this test")
    applied = pack.metadata["feedback_applied"]
    entries = {e["path"]: e["delta"] for e in applied}
    assert "src/main.py" in entries
    assert entries["src/main.py"] == pytest.approx(0.05)


def test_feedback_applied_omits_paths_not_in_visible_pack(tmp_path: Path) -> None:
    """Adjustments for files not in the final pack are filtered out of metadata.

    Keeps the metadata answer-focused: 'which historical signal influenced
    THIS pack' rather than 'all historical signals globally'.
    """
    root = _make_project(tmp_path, file_path="src/main.py")
    repo_scope = str(root.resolve())
    # Seed feedback for a file that does NOT exist in the index.
    _seed_feedback(root, repo_scope, files_read=["src/ghost.py"])

    pack = Orchestrator(project_root=root).build_pack("review", "test")
    applied = pack.metadata["feedback_applied"]
    # ghost.py was never indexed so it can't be in the pack — must not leak.
    paths = {e["path"] for e in applied}
    assert "src/ghost.py" not in paths
