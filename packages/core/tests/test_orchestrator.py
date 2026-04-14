"""Tests for Orchestrator: build_pack, last_pack, candidate classification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.interfaces import Symbol
from contracts.models import ContextPack
from core.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_db(db_path: Path) -> None:
    """Create a minimal SQLite database seeded with one symbol."""
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    with Database(db_path) as db:
        repo = SymbolRepository(db.connection)
        sym = Symbol(
            name="my_function",
            kind="function",
            file=Path("src/main.py"),
            line_start=1,
            line_end=5,
            language="python",
            signature="def my_function() -> None:",
            docstring="Does something.",
        )
        repo.add_bulk([sym], "default")


def _make_project(tmp_path: Path) -> Path:
    """Create a minimal project layout under tmp_path and return root."""
    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    db_path = cr_dir / "context-router.db"
    _seed_db(db_path)
    return tmp_path


# ---------------------------------------------------------------------------
# build_pack
# ---------------------------------------------------------------------------

def test_build_pack_review_returns_context_pack(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    pack = orch.build_pack("review", "check recent changes")
    assert isinstance(pack, ContextPack)
    assert pack.mode == "review"


def test_build_pack_implement_returns_context_pack(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    pack = orch.build_pack("implement", "add new endpoint")
    assert isinstance(pack, ContextPack)
    assert pack.mode == "implement"


def test_build_pack_stores_query(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("review", "my query")
    assert pack.query == "my query"


def test_build_pack_items_have_reason(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("implement", "")
    for item in pack.selected_items:
        assert item.reason, f"Item {item.title!r} has empty reason"


def test_build_pack_persists_last_pack(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    Orchestrator(project_root=root).build_pack("review", "test")
    assert (root / ".context-router" / "last-pack.json").exists()


def test_build_pack_persisted_file_is_valid_json(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    Orchestrator(project_root=root).build_pack("review", "")
    text = (root / ".context-router" / "last-pack.json").read_text()
    data = json.loads(text)
    assert data["mode"] == "review"


def test_build_pack_raises_on_missing_db(tmp_path: Path) -> None:
    (tmp_path / ".context-router").mkdir()
    orch = Orchestrator(project_root=tmp_path)
    with pytest.raises(FileNotFoundError):
        orch.build_pack("review", "")


def test_build_pack_token_stats(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("review", "")
    assert pack.total_est_tokens >= 0
    assert pack.baseline_est_tokens >= pack.total_est_tokens
    assert 0.0 <= pack.reduction_pct <= 100.0


# ---------------------------------------------------------------------------
# last_pack
# ---------------------------------------------------------------------------

def test_last_pack_returns_none_when_missing(tmp_path: Path) -> None:
    (tmp_path / ".context-router").mkdir()
    orch = Orchestrator(project_root=tmp_path)
    assert orch.last_pack() is None


def test_last_pack_roundtrip(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    original = orch.build_pack("implement", "roundtrip test")
    loaded = orch.last_pack()
    assert loaded is not None
    assert loaded.id == original.id
    assert loaded.mode == original.mode


# ---------------------------------------------------------------------------
# _find_project_root
# ---------------------------------------------------------------------------

def test_find_project_root_walks_up(tmp_path: Path) -> None:
    from core.orchestrator import _find_project_root

    (tmp_path / ".context-router").mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert _find_project_root(nested) == tmp_path


def test_find_project_root_raises_when_absent(tmp_path: Path) -> None:
    from core.orchestrator import _find_project_root

    with pytest.raises(FileNotFoundError):
        _find_project_root(tmp_path)


# ---------------------------------------------------------------------------
# _classify_for_implement (static helper)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("name", "kind", "file_path", "expected_source_type"),
    [
        ("main", "function", "app/main.py", "entrypoint"),
        ("create_app", "function", "app/factory.py", "entrypoint"),
        ("router", "function", "api/routes.py", "entrypoint"),
        ("MyModel", "class", "contracts/models.py", "contract"),
        ("UserSchema", "class", "schemas/user.py", "contract"),
        ("BaseHandler", "class", "handlers.py", "extension_point"),
        ("AbstractParser", "class", "parsers.py", "extension_point"),
        ("MyMixin", "class", "utils.py", "extension_point"),
        ("SomeProtocol", "class", "proto.py", "extension_point"),
        ("OrdinaryClass", "class", "logic.py", "file"),
        ("helper", "function", "utils.py", "file"),
        ("CONSTANT", "variable", "config.py", "file"),
    ],
)
def test_classify_for_implement(
    name: str, kind: str, file_path: str, expected_source_type: str
) -> None:
    source_type, confidence = Orchestrator._classify_for_implement(name, kind, file_path)
    assert source_type == expected_source_type
    assert 0.0 < confidence <= 1.0


# ---------------------------------------------------------------------------
# P0a: est_tokens includes metadata overhead
# ---------------------------------------------------------------------------

def test_est_tokens_includes_metadata_overhead(tmp_path: Path) -> None:
    """est_tokens must be > just the excerpt tokens (title + overhead added)."""
    from ranking import estimate_tokens

    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("implement", "")
    for item in pack.selected_items:
        raw_excerpt_tokens = estimate_tokens(item.excerpt)
        # est_tokens should include title + overhead (~40) on top of excerpt
        assert item.est_tokens > raw_excerpt_tokens, (
            f"Item {item.title!r}: est_tokens={item.est_tokens} "
            f"not greater than raw excerpt tokens={raw_excerpt_tokens}"
        )


def test_total_est_tokens_accounts_for_overhead(tmp_path: Path) -> None:
    """total_est_tokens must exceed the sum of excerpt-only estimates."""
    from ranking import estimate_tokens

    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("implement", "")
    excerpt_only_total = sum(estimate_tokens(i.excerpt) for i in pack.selected_items)
    assert pack.total_est_tokens > excerpt_only_total


# ---------------------------------------------------------------------------
# P3: Pagination
# ---------------------------------------------------------------------------

def test_pagination_page_0_returns_first_slice(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    # Seed more symbols so there are items to paginate
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository
    from contracts.interfaces import Symbol

    with Database(root / ".context-router" / "context-router.db") as db:
        syms = [
            Symbol(name=f"func_{i}", kind="function", file=Path(f"src/mod_{i}.py"),
                   line_start=1, line_end=5, language="python",
                   signature=f"def func_{i}(): pass", docstring="")
            for i in range(10)
        ]
        SymbolRepository(db.connection).add_bulk(syms, "default")

    pack = Orchestrator(project_root=root).build_pack("implement", "", page=0, page_size=3)
    assert len(pack.selected_items) <= 3


def test_pagination_has_more_when_more_items_exist(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository
    from contracts.interfaces import Symbol

    with Database(root / ".context-router" / "context-router.db") as db:
        syms = [
            Symbol(name=f"fn_{i}", kind="function", file=Path(f"src/m_{i}.py"),
                   line_start=1, line_end=3, language="python",
                   signature=f"def fn_{i}(): pass", docstring="")
            for i in range(20)
        ]
        SymbolRepository(db.connection).add_bulk(syms, "default")

    pack = Orchestrator(project_root=root).build_pack("implement", "", page=0, page_size=3)
    # With 20+ symbols, page 0 of size 3 should signal more pages
    assert pack.has_more is True
    assert pack.total_items > 3


def test_pagination_last_page_has_no_more(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack_all = Orchestrator(project_root=root).build_pack("implement", "")
    total = len(pack_all.selected_items)
    if total == 0:
        return  # nothing to test

    # Request a single huge page — should get everything
    pack_paged = Orchestrator(project_root=root).build_pack(
        "implement", "", page=0, page_size=total + 100
    )
    assert pack_paged.has_more is False


def test_no_pagination_has_more_false(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("implement", "")
    assert pack.has_more is False
    assert pack.total_items == 0
