"""Tests for v4.4.2 Phase 7 — docs-only-diff carve-out for the widening gate.

Phase 3's query-driven candidate widening is suppressed whenever the diff
is non-empty, on the assumption that a real diff is the authoritative
signal. PRs whose entire diff is a release-notes.md / CHANGELOG.md bump
(e.g. fastapi T1/T3 in the harness) are now treated as "no diff" for the
widening gate ONLY — the `changed_files` set itself is unchanged, so
diff-aware boost and the ``changed_file`` source-type still see it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from contracts.models import ContextPack
from core.orchestrator import (
    Orchestrator,
    _is_docs_only_diff,
    _is_docs_path,
)


# ---------------------------------------------------------------------------
# Unit tests: _is_docs_only_diff / _is_docs_path classifiers
# ---------------------------------------------------------------------------


def test_docs_only_diff_classifier_recognises_md_rst_changelog() -> None:
    assert _is_docs_only_diff({"release-notes.md"}) is True
    assert _is_docs_only_diff({"docs/guide.rst"}) is True
    assert _is_docs_only_diff({"CHANGELOG.md"}) is True
    assert _is_docs_only_diff({"README.md", "docs/api.md"}) is True


def test_docs_only_diff_classifier_rejects_mixed_diff() -> None:
    # Mixed: any code file alongside docs → not docs-only.
    assert _is_docs_only_diff({"src/main.py", "release-notes.md"}) is False
    # Pure code.
    assert _is_docs_only_diff({"app/api/v1.py"}) is False
    # .txt outside docs/ is not docs (could be a real source file).
    assert _is_docs_only_diff({"src/foo.txt"}) is False


def test_docs_only_diff_classifier_handles_empty() -> None:
    # Empty changed_files means "no diff at all" — the classifier returns
    # False so the existing ``not changed_files`` branch in the gate is
    # the one that fires (rather than this carve-out).
    assert _is_docs_only_diff(set()) is False
    assert _is_docs_only_diff([]) is False


def test_docs_path_classifier_handles_top_level_markers() -> None:
    # Top-level marker files without a docs-suffix still classify as docs.
    assert _is_docs_path("LICENSE") is True
    assert _is_docs_path("CONTRIBUTING.md") is True
    assert _is_docs_path("NOTICE") is True
    assert _is_docs_path("HISTORY.rst") is True
    assert _is_docs_path("SECURITY.md") is True
    # Lowercase "license" inside a code directory must NOT classify as
    # docs (it's a real Python module that happens to be named license.py).
    assert _is_docs_path("src/license.py") is False


# ---------------------------------------------------------------------------
# Integration tests: widening end-to-end via Orchestrator.build_pack
# ---------------------------------------------------------------------------


def _seed_one_symbol(
    db_path: Path,
    *,
    symbol_name: str = "oauth2_helper",
    file_path: str = "src/oauth2.py",
) -> None:
    """Seed the database with a single symbol the query is expected to match."""
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    with Database(db_path) as db:
        repo = SymbolRepository(db.connection)
        repo.add_bulk(
            [
                Symbol(
                    name=symbol_name,
                    kind="function",
                    file=Path(file_path),
                    line_start=1,
                    line_end=5,
                    language="python",
                    signature=f"def {symbol_name}() -> None:",
                    docstring="OAuth2 helper.",
                )
            ],
            "default",
        )


def _make_project(
    tmp_path: Path,
    *,
    source_file: str = "src/oauth2.py",
    symbol_name: str = "oauth2_helper",
) -> Path:
    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    src_path = tmp_path / source_file
    src_path.parent.mkdir(parents=True, exist_ok=True)
    src_path.write_text(f"def {symbol_name}() -> None:\n    pass\n")
    _seed_one_symbol(
        cr_dir / "context-router.db",
        symbol_name=symbol_name,
        file_path=source_file,
    )
    return tmp_path


def test_widening_fires_on_docs_only_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Docs-only diff (e.g. release-notes.md) should NOT suppress widening:
    the seeded oauth2.py file should appear with source_type=query_match."""
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    # Stub the diff to a single docs file. Phase 7 should treat this as
    # "no diff" for the widening gate — query tokens get computed and
    # the seeded oauth2 symbol gets lifted to source_type=query_match.
    monkeypatch.setattr(
        Orchestrator,
        "_get_changed_files",
        lambda self: {"release-notes.md"},
    )
    pack = orch.build_pack("review", "fix oauth2 client_secret docstring")
    assert isinstance(pack, ContextPack)
    assert pack.selected_items, "expected at least one candidate"
    query_match_items = [
        i for i in pack.selected_items if i.source_type == "query_match"
    ]
    assert query_match_items, (
        "expected a query_match item on a docs-only diff (Phase 7); got "
        f"source_types: {[i.source_type for i in pack.selected_items]}"
    )
    # And the lifted item should be the GT-equivalent oauth2.py symbol.
    paths = {Path(i.path_or_ref).name for i in query_match_items}
    assert "oauth2.py" in paths


def test_widening_suppressed_on_code_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real code diff should still suppress widening (v4.4.1 behaviour
    preserved). The seeded oauth2 symbol must NOT get a query_match label."""
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    # Stub the diff to a code file unrelated to the seeded symbol. Phase 7
    # must NOT widen here — widening on top of a real diff regresses F1.
    monkeypatch.setattr(
        Orchestrator,
        "_get_changed_files",
        lambda self: {"src/main.py"},
    )
    pack = orch.build_pack("review", "fix oauth2 client_secret docstring")
    assert pack.selected_items, "expected at least one candidate"
    query_match_items = [
        i for i in pack.selected_items if i.source_type == "query_match"
    ]
    assert not query_match_items, (
        "expected NO query_match items when the diff has real code "
        f"(authoritative-diff behaviour preserved); got: {query_match_items}"
    )
