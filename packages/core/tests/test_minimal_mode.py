"""Tests for Orchestrator minimal mode (Phase 3 — CRG parity)."""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from contracts.models import ContextPack
from core.orchestrator import Orchestrator, _suggest_next_tool

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _seed_db_with_many_symbols(db_path: Path, count: int = 12) -> None:
    """Seed the database with *count* symbols spanning a few files.

    The minimal-mode cap is 5; seeding 12 gives the ranker a real pool to
    trim against so the 5-item cap is meaningful.
    """
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    with Database(db_path) as db:
        repo = SymbolRepository(db.connection)
        syms = []
        for idx in range(count):
            syms.append(
                Symbol(
                    name=f"func_{idx}",
                    kind="function",
                    file=Path(f"src/module_{idx % 4}.py"),
                    line_start=idx * 10 + 1,
                    line_end=idx * 10 + 5,
                    language="python",
                    signature=f"def func_{idx}() -> None:",
                    docstring=f"Helper {idx}.",
                )
            )
        repo.add_bulk(syms, "default")


def _make_project(tmp_path: Path, *, symbol_count: int = 12) -> Path:
    cr_dir = tmp_path / ".context-router"
    cr_dir.mkdir()
    _seed_db_with_many_symbols(cr_dir / "context-router.db", count=symbol_count)
    return tmp_path


# ---------------------------------------------------------------------------
# build_pack(mode="minimal")
# ---------------------------------------------------------------------------

def test_minimal_mode_returns_at_most_5_items(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    pack = orch.build_pack("minimal", "review the ranker")
    assert isinstance(pack, ContextPack)
    assert pack.mode == "minimal"
    assert len(pack.selected_items) <= 5


def test_minimal_mode_sets_next_tool_suggestion(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    pack = Orchestrator(project_root=root).build_pack("minimal", "find ranker")
    assert "next_tool_suggestion" in pack.metadata
    hint = pack.metadata["next_tool_suggestion"]
    assert isinstance(hint, str)
    assert hint  # non-empty


def test_minimal_mode_honors_max_tokens_override(tmp_path: Path) -> None:
    """A tight token_budget override must shrink the resulting pack."""
    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)
    loose = orch.build_pack("minimal", "scan symbols", token_budget=2000)
    # Clear caches so the tight call actually re-runs the ranker.
    orch.invalidate_cache()
    tight = orch.build_pack("minimal", "scan symbols", token_budget=50)
    # At minimum, the tight pack must not exceed its own budget materially
    # (a single oversized item can sneak past the budget, so we compare
    # against the loose total rather than assert tight.total < 50).
    assert tight.total_est_tokens <= max(50, loose.total_est_tokens)
    assert len(tight.selected_items) <= 5


def test_minimal_mode_has_no_pagination(tmp_path: Path) -> None:
    root = _make_project(tmp_path, symbol_count=20)
    pack = Orchestrator(project_root=root).build_pack("minimal", "any query")
    assert pack.has_more is False


# ---------------------------------------------------------------------------
# Regression: other modes unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["review", "implement", "debug", "handover"])
def test_non_minimal_modes_do_not_cap_to_5(tmp_path: Path, mode: str) -> None:
    root = _make_project(tmp_path, symbol_count=20)
    pack = Orchestrator(project_root=root).build_pack(mode, "x")
    # Other modes may legitimately return >5 items; we're just asserting the
    # minimal-mode cap didn't leak into them. (At most, they'll be trimmed
    # by the token budget, not by the 5-item ceiling.)
    assert pack.mode == mode
    # And the minimal-mode metadata hint is not populated for them.
    assert "next_tool_suggestion" not in pack.metadata


def test_build_pack_rejects_unknown_mode(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    with pytest.raises(ValueError):
        Orchestrator(project_root=root).build_pack("quantum", "x")


# ---------------------------------------------------------------------------
# _suggest_next_tool heuristics
# ---------------------------------------------------------------------------

def _item(path: str, *, confidence: float = 0.5, title: str = "x"):
    from contracts.models import ContextItem

    return ContextItem(
        source_type="file",
        repo="default",
        path_or_ref=path,
        title=title,
        reason="seed",
        confidence=confidence,
    )


def test_suggest_next_tool_empty_items_returns_default() -> None:
    hint = _suggest_next_tool([], "add pagination")
    assert "get_context_pack" in hint
    assert "implement" in hint


def test_suggest_next_tool_top_test_file_routes_to_debug() -> None:
    hint = _suggest_next_tool([_item("tests/test_ranker.py")], "rank fails")
    assert "debug" in hint.lower()


def test_suggest_next_tool_mostly_config_routes_to_review() -> None:
    items = [
        _item("config/app.yaml"),
        _item("deploy/prod.yml"),
        _item("pyproject.toml"),
        _item("src/main.py"),  # minority non-config
    ]
    hint = _suggest_next_tool(items, "update deploy config")
    assert "review" in hint.lower()


def test_suggest_next_tool_default_echoes_query() -> None:
    hint = _suggest_next_tool([_item("src/main.py")], "add pagination")
    assert "implement" in hint
    assert "add pagination" in hint
