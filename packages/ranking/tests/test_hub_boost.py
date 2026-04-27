"""Integration tests for the Phase-3 hub / bridge ranking boost.

Covers the three behavioural guarantees in the outcome registry entry
``hub-bridge-ranking-signals``:

1. With the flag on, a high-inbound-degree symbol outranks a
   similarly-matched non-hub peer.
2. With the flag off, ranking order is identical to the pre-boost
   baseline (regression gate — the negative case in the DoD).
3. Items without a resolvable ``symbol_id`` (e.g. memory / decision
   entries) are passed through untouched, not crashed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.interfaces import Symbol
from contracts.models import ContextItem
from ranking.ranker import ContextRanker
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Project root laid out the way ``_discover_db_path`` walks to."""
    root = tmp_path / "proj"
    (root / ".context-router").mkdir(parents=True)
    (root / "src").mkdir()
    return root


@pytest.fixture()
def seeded_db(project_root: Path):
    """Index two files (``hub.py``, ``leaf.py``) with known hub structure.

    ``hub()`` has six inbound ``calls`` edges; ``leaf()`` has one.  Both
    symbols therefore appear in the ``symbols`` table and can be
    resolved by the ranker's ``(path, name) → id`` lookup.
    """
    hub_path = project_root / "src" / "hub.py"
    leaf_path = project_root / "src" / "leaf.py"
    hub_path.write_text("def hub(items):\n    return items\n")
    leaf_path.write_text("def leaf(items):\n    return items\n")

    db_path = project_root / ".context-router" / "context-router.db"
    db = Database(db_path)
    db.initialize()
    sym_repo = SymbolRepository(db.connection)
    edge_repo = EdgeRepository(db.connection)
    repo = "default"

    # Two candidate symbols (the items we'll rank).
    sym_repo.add(
        Symbol(
            name="hub",
            kind="function",
            file=hub_path,
            line_start=1,
            line_end=2,
            language="python",
        ),
        repo,
    )
    sym_repo.add(
        Symbol(
            name="leaf",
            kind="function",
            file=leaf_path,
            line_start=1,
            line_end=2,
            language="python",
        ),
        repo,
    )

    # Six caller symbols that reference `hub`; one that references `leaf`.
    for i in range(6):
        sym_repo.add(
            Symbol(
                name=f"caller{i}",
                kind="function",
                file=project_root / "src" / f"c{i}.py",
                line_start=1,
                line_end=2,
                language="python",
            ),
            repo,
        )

    hub_id = sym_repo.get_id_by_name(repo, "hub")
    leaf_id = sym_repo.get_id_by_name(repo, "leaf")
    assert hub_id is not None and leaf_id is not None

    for i in range(6):
        cid = sym_repo.get_id_by_name(repo, f"caller{i}")
        edge_repo.add_raw(repo, cid, hub_id, "calls")
    edge_repo.add_raw(
        repo, sym_repo.get_id_by_name(repo, "caller0"), leaf_id, "calls"
    )
    yield db
    db.close()


def _item(*, title: str, path: Path, confidence: float = 0.5) -> ContextItem:
    return ContextItem(
        source_type="file",
        repo="default",
        path_or_ref=str(path),
        title=title,
        excerpt="rank items for ingestion pipeline",
        reason="",
        confidence=confidence,
        est_tokens=100,
    )


# ---------------------------------------------------------------------------
# Behavioural guarantees
# ---------------------------------------------------------------------------


def test_hub_boost_on_lifts_the_hub_above_equivalent_peer(
    project_root: Path, seeded_db
) -> None:
    """Flag on → ``hub`` outranks ``leaf`` despite identical structural conf."""
    items = [
        _item(title="hub", path=project_root / "src" / "hub.py", confidence=0.5),
        _item(title="leaf", path=project_root / "src" / "leaf.py", confidence=0.5),
    ]
    ranker = ContextRanker(token_budget=0, use_hub_boost=True)
    ranked = ranker.rank(items, "rank items for ingestion pipeline", "implement")
    titles = [i.title for i in ranked]
    assert titles[0] == "hub", f"expected hub first, got {titles}"


def test_hub_boost_off_preserves_baseline_order(
    project_root: Path, seeded_db
) -> None:
    """Flag off → order matches the pre-boost ranker (regression gate).

    This is the negative case from the outcome spec: turning the flag
    off MUST return baseline order, so we compare against a ranker
    constructed the old way (no kwarg at all).
    """
    items = [
        _item(title="leaf", path=project_root / "src" / "leaf.py", confidence=0.5),
        _item(title="hub", path=project_root / "src" / "hub.py", confidence=0.5),
    ]
    off = ContextRanker(token_budget=0, use_hub_boost=False).rank(
        list(items), "rank items", "implement"
    )
    baseline = ContextRanker(token_budget=0).rank(
        list(items), "rank items", "implement"
    )
    assert [i.title for i in off] == [i.title for i in baseline]
    assert [round(i.confidence, 6) for i in off] == [
        round(i.confidence, 6) for i in baseline
    ]


def test_hub_boost_env_var_toggles_the_flag(
    project_root: Path, seeded_db, monkeypatch
) -> None:
    """``CAPABILITIES_HUB_BOOST=1`` must activate the boost without constructor args."""
    items = [
        _item(title="hub", path=project_root / "src" / "hub.py", confidence=0.5),
        _item(title="leaf", path=project_root / "src" / "leaf.py", confidence=0.5),
    ]
    monkeypatch.setenv("CAPABILITIES_HUB_BOOST", "1")
    # v4.4: hub_boost is gated to handover mode only — exercise it there.
    on = ContextRanker(token_budget=0).rank(list(items), "rank items", "handover")
    monkeypatch.setenv("CAPABILITIES_HUB_BOOST", "0")
    off = ContextRanker(token_budget=0).rank(list(items), "rank items", "handover")
    assert on[0].title == "hub"
    # Off path should leave the two identical-confidence peers tied, so
    # their stable-sort order depends only on input ordering.
    assert sorted(i.title for i in off) == sorted(i.title for i in on)
    # But the ``hub`` confidence MUST be higher in the on-path than
    # the off-path — otherwise the boost did not take effect.
    on_hub = next(i for i in on if i.title == "hub")
    off_hub = next(i for i in off if i.title == "hub")
    assert on_hub.confidence > off_hub.confidence


def test_hub_boost_skips_items_without_resolvable_symbol_id(
    project_root: Path, seeded_db
) -> None:
    """Memory / decision items (no matching symbols row) must not crash.

    The ranker applies BM25 + hub_boost. Without a matching symbol the
    hub_boost layer must pass the item through untouched — so the
    on-path confidence MUST equal the off-path confidence (the BM25
    baseline) for the ghost item, while the hub item is lifted.
    """
    memory_item = ContextItem(
        source_type="memory",
        repo="default",
        path_or_ref=str(project_root / "src" / "ghost.py"),
        title="ghost (not in symbols)",
        excerpt="observation text",
        reason="",
        confidence=0.5,
        est_tokens=100,
    )
    seed = [
        memory_item,
        _item(title="hub", path=project_root / "src" / "hub.py", confidence=0.5),
    ]
    # v4.4: hub_boost is gated to handover mode only.
    on = ContextRanker(token_budget=0, use_hub_boost=True).rank(
        list(seed), "rank items", "handover"
    )
    off = ContextRanker(token_budget=0, use_hub_boost=False).rank(
        list(seed), "rank items", "handover"
    )
    on_ghost = next(i for i in on if i.title.startswith("ghost"))
    off_ghost = next(i for i in off if i.title.startswith("ghost"))
    assert on_ghost.confidence == pytest.approx(off_ghost.confidence, abs=1e-9)
    # And the hub item MUST be lifted relative to the off path.
    on_hub = next(i for i in on if i.title == "hub")
    off_hub = next(i for i in off if i.title == "hub")
    assert on_hub.confidence > off_hub.confidence


def test_hub_boost_capped_at_plus_ten(project_root: Path, seeded_db) -> None:
    """The boost helper alone must add at most ``+0.10`` confidence.

    We compare on- vs off-path for the same item so BM25's contribution
    cancels out — the delta is purely the hub/bridge boost.
    """
    seed = [_item(title="hub", path=project_root / "src" / "hub.py", confidence=0.5)]
    # v4.4: hub_boost is gated to handover mode only.
    on = ContextRanker(token_budget=0, use_hub_boost=True).rank(
        list(seed), "rank items", "handover"
    )
    off = ContextRanker(token_budget=0, use_hub_boost=False).rank(
        list(seed), "rank items", "handover"
    )
    delta = on[0].confidence - off[0].confidence
    assert 0 < delta <= 0.10 + 1e-6, (
        f"hub boost delta must be in (0, 0.10]; got {delta}"
    )
    # Result never exceeds the global confidence ceiling.
    assert on[0].confidence <= 0.95 + 1e-6


def test_hub_boost_silent_when_no_db_found(capsys) -> None:
    """If no project DB is discoverable, we warn once and pass items through."""
    items = [
        ContextItem(
            source_type="file",
            repo="default",
            path_or_ref="bogus-path-no-project.py",
            title="ghost",
            excerpt="text",
            reason="",
            confidence=0.5,
            est_tokens=100,
        )
    ]
    ranker = ContextRanker(token_budget=0, use_hub_boost=True)
    # v4.4: hub_boost is gated to handover mode only.
    out = ranker.rank(list(items), "q", "handover")
    assert len(out) == 1
    captured = capsys.readouterr()
    assert "hub_boost" in captured.err
