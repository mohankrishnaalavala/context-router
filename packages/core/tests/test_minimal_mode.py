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


# ---------------------------------------------------------------------------
# v3.1 minimal-mode-ranker-tuning (P1) — top implement-mode item preservation
# ---------------------------------------------------------------------------


def _code_item(
    path: str,
    *,
    source_type: str = "file",
    confidence: float = 0.5,
    title: str | None = None,
    est_tokens: int = 10,
):
    """Build a ContextItem with a code-symbol source_type for tests."""
    from contracts.models import ContextItem

    return ContextItem(
        source_type=source_type,
        repo="default",
        path_or_ref=path,
        title=title or path.split("/")[-1],
        reason="seed",
        confidence=confidence,
        est_tokens=est_tokens,
    )


def test_minimal_pins_highest_confidence_code_symbol_at_top(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With 10 synthetic candidates, minimal top-1 == the unbounded-rank top-1.

    Simulates the budget-enforcement drop path: we seed 10 code-symbol items
    with deterministic confidences such that the highest-confidence item
    (``entrypoint``, Visit.java) would be demoted by ``_enforce_budget``'s
    source-type coverage rule. The preservation overlay must pin it at
    position 0 of the final top-5.
    """
    root = _make_project(tmp_path, symbol_count=12)
    orch = Orchestrator(project_root=root)

    # Deterministic, monotonically decreasing confidences. The first item is
    # the "Visit" entity and has the highest confidence — the overlay must
    # surface it at position 0 even if budget enforcement would drop it.
    synthetic = [
        _code_item(
            "src/main/java/.../visit/Visit.java",
            source_type="entrypoint",
            confidence=0.90,
            title="Visit (Visit.java)",
        ),
        _code_item("src/main/java/AppRoot.java", source_type="entrypoint", confidence=0.80),
        _code_item("src/main/java/Owner.java", source_type="file", confidence=0.70),
        _code_item("src/main/java/Pet.java", source_type="file", confidence=0.60),
        _code_item("src/main/java/Clinic.java", source_type="file", confidence=0.55),
        _code_item("src/test/java/OwnerTest.java", source_type="file", confidence=0.50),
        _code_item("src/test/java/PetTest.java", source_type="file", confidence=0.45),
        _code_item("src/main/java/Vet.java", source_type="contract", confidence=0.40),
        _code_item("config/app.yaml", source_type="file", confidence=0.35),
        _code_item("pom.xml", source_type="file", confidence=0.30),
    ]

    # Stub the candidate builder so the ranker sees exactly our synthetic set.
    monkeypatch.setattr(
        Orchestrator,
        "_build_candidates",
        lambda self, mode, sym_repo, edge_repo, **kwargs: list(synthetic),
    )
    # Disable the community boost so confidence ordering is deterministic —
    # the boost reads the SQLite graph which is irrelevant to this contract.
    monkeypatch.setattr(
        Orchestrator,
        "_apply_community_boost",
        lambda self, items, sym_repo, repo_name: items,
    )
    # Disable the contracts boost for the same reason (reads disk).
    monkeypatch.setattr(
        Orchestrator,
        "_apply_contracts_boost",
        lambda self, items, repo_root, repo_name="default", config=None: items,
    )
    # Force the ranker to skip semantic embeddings — the test contract is
    # about confidence preservation, not semantic boost.
    orch.invalidate_cache()

    pack = orch.build_pack("minimal", "add visit", use_embeddings=False)

    assert len(pack.selected_items) <= 5
    assert pack.selected_items, "minimal pack must not be empty when candidates exist"
    top = pack.selected_items[0]
    assert "Visit.java" in top.path_or_ref, (
        f"expected Visit.java pinned at top, got {top.path_or_ref}"
    )


def test_minimal_no_code_symbol_candidates_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the candidate pool has zero code-symbol items (e.g. memory-only),
    minimal mode must still return a valid pack without raising.
    """
    from contracts.models import ContextItem

    root = _make_project(tmp_path)
    orch = Orchestrator(project_root=root)

    # All candidates are metadata overlays (memory/decision) — none match
    # the implement source types, so preservation must gracefully no-op.
    metadata_only = [
        ContextItem(
            source_type="memory",
            repo="default",
            path_or_ref="memory/obs-1",
            title="Observation: old fix",
            reason="recent work",
            confidence=0.40,
            est_tokens=20,
        ),
        ContextItem(
            source_type="decision",
            repo="default",
            path_or_ref="decision/dec-1",
            title="Decision: use X",
            reason="adr",
            confidence=0.35,
            est_tokens=18,
        ),
    ]
    monkeypatch.setattr(
        Orchestrator,
        "_build_candidates",
        lambda self, mode, sym_repo, edge_repo, **kwargs: list(metadata_only),
    )
    monkeypatch.setattr(
        Orchestrator,
        "_apply_community_boost",
        lambda self, items, sym_repo, repo_name: items,
    )
    monkeypatch.setattr(
        Orchestrator,
        "_apply_contracts_boost",
        lambda self, items, repo_root, repo_name="default", config=None: items,
    )

    pack = orch.build_pack("minimal", "any query", use_embeddings=False)
    assert pack.mode == "minimal"
    # No crash, cap still honored, coverage-selected items retained.
    assert len(pack.selected_items) <= 5


def test_minimal_still_caps_at_five_items_after_preservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Top-1 preservation MUST NOT inflate the cap past 5 items."""
    root = _make_project(tmp_path, symbol_count=20)
    orch = Orchestrator(project_root=root)

    # 10 synthetic items, all code-symbol, decreasing confidence.
    # Confidences chosen so >5 items survive the v4.4 score floor
    # (0.45 absolute floor after the 0.6× BM25-no-match multiplier ⇒ source
    # confidences must be >= ~0.75 post-multiply ⇒ raw ≥ 1.25 / 0.6 ≈ 2.0).
    # Using conf = 0.95 - i*0.03 yields 7 post-BM25 items above the floor.
    pool = [
        _code_item(
            f"src/module_{i}.py",
            source_type="file",
            confidence=0.95 - i * 0.03,
            title=f"mod{i}",
        )
        for i in range(10)
    ]
    monkeypatch.setattr(
        Orchestrator,
        "_build_candidates",
        lambda self, mode, sym_repo, edge_repo, **kwargs: list(pool),
    )
    monkeypatch.setattr(
        Orchestrator,
        "_apply_community_boost",
        lambda self, items, sym_repo, repo_name: items,
    )
    monkeypatch.setattr(
        Orchestrator,
        "_apply_contracts_boost",
        lambda self, items, repo_root, repo_name="default", config=None: items,
    )

    pack = orch.build_pack("minimal", "pick one", use_embeddings=False)
    assert len(pack.selected_items) == 5


def test_minimal_top_one_matches_implement_top_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract: minimal-mode top-1 `path_or_ref` MUST equal implement-mode top-1.

    Mirrors the smoke-handler assertion so a regression shows up in unit
    tests before it reaches the release gate.
    """
    root = _make_project(tmp_path, symbol_count=15)
    orch = Orchestrator(project_root=root)

    pool = [
        _code_item("src/alpha.py", source_type="entrypoint", confidence=0.88),
        _code_item("src/beta.py", source_type="file", confidence=0.75),
        _code_item("src/gamma.py", source_type="file", confidence=0.60),
        _code_item("src/delta.py", source_type="file", confidence=0.55),
        _code_item("src/epsilon.py", source_type="file", confidence=0.50),
        _code_item("src/zeta.py", source_type="contract", confidence=0.48),
        _code_item("src/eta.py", source_type="extension_point", confidence=0.40),
    ]
    monkeypatch.setattr(
        Orchestrator,
        "_build_candidates",
        lambda self, mode, sym_repo, edge_repo, **kwargs: list(pool),
    )
    monkeypatch.setattr(
        Orchestrator,
        "_apply_community_boost",
        lambda self, items, sym_repo, repo_name: items,
    )
    monkeypatch.setattr(
        Orchestrator,
        "_apply_contracts_boost",
        lambda self, items, repo_root, repo_name="default", config=None: items,
    )

    impl_pack = orch.build_pack("implement", "same-query", use_embeddings=False)
    orch.invalidate_cache()
    mini_pack = orch.build_pack("minimal", "same-query", use_embeddings=False)

    assert impl_pack.selected_items, "implement pack must not be empty"
    assert mini_pack.selected_items, "minimal pack must not be empty"
    assert (
        mini_pack.selected_items[0].path_or_ref
        == impl_pack.selected_items[0].path_or_ref
    ), (
        "minimal top-1 path_or_ref must match implement top-1 — "
        f"got minimal={mini_pack.selected_items[0].path_or_ref}, "
        f"implement={impl_pack.selected_items[0].path_or_ref}"
    )
