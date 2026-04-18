"""Tests for debug-mode flow-level annotation (Phase 4 Wave 1).

Covers:
  * Debug-mode pack annotates items with ``entry -> leaf`` labels when the
    graph has detectable flows (requirement 3).
  * Empty graph / no flows -> every item's ``flow`` is None and
    ``pack.metadata["note"]`` explains why (requirement 4).
  * Non-debug modes (implement/review/handover/minimal) never populate
    ``flow`` (requirement 5).
  * The underlying ``_apply_debug_flows`` helper threshold logic reports
    ``note`` when fewer than 3 of the top 5 items are annotated.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from contracts.models import ContextItem
from core.orchestrator import Orchestrator
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_symbol(name: str, kind: str, file_path: str) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        file=Path(file_path),
        line_start=1,
        line_end=5,
        language="python",
    )


def _seed_flow_graph(db_path: Path) -> dict[str, int]:
    """Seed the DB with a small graph containing 3 full entry -> leaf flows.

    Returns the ``name -> symbol_id`` map so tests can cross-reference.
    """
    with Database(db_path) as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)

        ids: dict[str, int] = {}
        for name, kind, fp in [
            ("get_owner", "function", "/app/ctrl_owner.py"),
            ("find_owner", "method", "/app/svc_owner.py"),
            ("select_owner", "method", "/app/db_owner.py"),
            ("get_pet", "function", "/app/ctrl_pet.py"),
            ("find_pet", "method", "/app/svc_pet.py"),
            ("get_visit", "function", "/app/ctrl_visit.py"),
            ("record_visit", "method", "/app/svc_visit.py"),
        ]:
            ids[name] = sym_repo.add(_mk_symbol(name, kind, fp), "default")

        # Three flows: owner (3 hops), pet (1 hop), visit (1 hop)
        for a, b in [
            ("get_owner", "find_owner"),
            ("find_owner", "select_owner"),
            ("get_pet", "find_pet"),
            ("get_visit", "record_visit"),
        ]:
            edge_repo.add_raw("default", ids[a], ids[b], "calls")

        return ids


def _make_item(
    *, title: str, path_or_ref: str, source_type: str = "file", confidence: float = 0.5
) -> ContextItem:
    return ContextItem(
        source_type=source_type,
        repo="default",
        path_or_ref=path_or_ref,
        title=title,
        reason="",
        confidence=confidence,
    )


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """Build a fake project with a seeded flow graph."""
    (tmp_path / ".context-router").mkdir()
    _seed_flow_graph(tmp_path / ".context-router" / "context-router.db")
    return tmp_path


# ---------------------------------------------------------------------------
# _apply_debug_flows — helper contract
# ---------------------------------------------------------------------------


def test_apply_debug_flows_annotates_top_items(project: Path):
    """Items whose symbol participates in a flow get a non-null ``flow`` label."""
    orch = Orchestrator(project_root=project)
    items = [
        _make_item(
            title="get_owner (ctrl_owner.py)",
            path_or_ref="/app/ctrl_owner.py",
            confidence=0.9,
        ),
        _make_item(
            title="find_owner (svc_owner.py)",
            path_or_ref="/app/svc_owner.py",
            confidence=0.85,
        ),
        _make_item(
            title="get_pet (ctrl_pet.py)",
            path_or_ref="/app/ctrl_pet.py",
            confidence=0.8,
        ),
        _make_item(
            title="get_visit (ctrl_visit.py)",
            path_or_ref="/app/ctrl_visit.py",
            confidence=0.75,
        ),
        _make_item(
            title="select_owner (db_owner.py)",
            path_or_ref="/app/db_owner.py",
            confidence=0.7,
        ),
    ]

    with Database(project / ".context-router" / "context-router.db") as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        annotated, note = orch._apply_debug_flows(items, sym_repo, edge_repo)

    # All five top items hit a flow — note is None (threshold met).
    assert note is None
    assert all(i.flow for i in annotated)
    # get_owner is itself an entry -> its flow label starts with "get_owner".
    assert annotated[0].flow.startswith("get_owner")
    # find_owner is mid-path -> its flow's entry is still get_owner.
    assert annotated[1].flow.startswith("get_owner")


def test_apply_debug_flows_empty_graph_returns_note(tmp_path: Path):
    """Requirement 4: empty graph -> every flow is None, with a note."""
    (tmp_path / ".context-router").mkdir()
    # Create the DB but add no symbols/edges.
    db_path = tmp_path / ".context-router" / "context-router.db"
    with Database(db_path) as db:
        _ = db.connection  # trigger migrations / table creation

    orch = Orchestrator(project_root=tmp_path)
    items = [_make_item(title="x (a.py)", path_or_ref="/a.py")]

    with Database(db_path) as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        annotated, note = orch._apply_debug_flows(items, sym_repo, edge_repo)

    assert note is not None
    assert "no flows detected" in note
    assert all(i.flow is None for i in annotated)


def test_apply_debug_flows_below_threshold_attaches_note(project: Path):
    """If fewer than 3 of the top 5 items resolve to a flow-member symbol,
    the note is set (outcome threshold)."""
    orch = Orchestrator(project_root=project)
    # Only the first item matches a symbol in the seeded graph.
    items = [
        _make_item(
            title="get_owner (ctrl_owner.py)",
            path_or_ref="/app/ctrl_owner.py",
        ),
        _make_item(title="unknown_1 (nope.py)", path_or_ref="/app/nope.py"),
        _make_item(title="unknown_2 (nope.py)", path_or_ref="/app/nope.py"),
        _make_item(title="unknown_3 (nope.py)", path_or_ref="/app/nope.py"),
        _make_item(title="unknown_4 (nope.py)", path_or_ref="/app/nope.py"),
    ]

    with Database(project / ".context-router" / "context-router.db") as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        annotated, note = orch._apply_debug_flows(items, sym_repo, edge_repo)

    assert note is not None
    assert "flows available for only 1" in note
    assert annotated[0].flow is not None
    assert all(i.flow is None for i in annotated[1:])


def test_apply_debug_flows_no_items_is_noop(project: Path):
    """Empty item list returns empty without erroring."""
    orch = Orchestrator(project_root=project)
    with Database(project / ".context-router" / "context-router.db") as db:
        sym_repo = SymbolRepository(db.connection)
        edge_repo = EdgeRepository(db.connection)
        annotated, note = orch._apply_debug_flows([], sym_repo, edge_repo)
    assert annotated == []
    assert note is None


# ---------------------------------------------------------------------------
# build_pack — end-to-end mode check
# ---------------------------------------------------------------------------


def test_build_pack_debug_annotates_flows(project: Path):
    """Requirement: a debug-mode pack populates ``flow`` on items that live
    in a flow; non-matching items stay at ``flow=None``.
    """
    orch = Orchestrator(project_root=project)
    pack = orch.build_pack(mode="debug", query="owner lookup failure")

    assert pack.mode == "debug"
    # At least one item should get a flow label, given the seeded graph.
    with_flow = [i for i in pack.selected_items if i.flow]
    assert with_flow, pack.selected_items


def test_build_pack_implement_never_sets_flow(project: Path):
    """Requirement 5: non-debug modes leave ``flow`` at None."""
    orch = Orchestrator(project_root=project)
    pack = orch.build_pack(mode="implement", query="add owner endpoint")
    assert all(i.flow is None for i in pack.selected_items)


def test_build_pack_review_never_sets_flow(project: Path):
    """Requirement 5: review mode never sets ``flow``."""
    orch = Orchestrator(project_root=project)
    pack = orch.build_pack(mode="review", query="owner refactor")
    assert all(i.flow is None for i in pack.selected_items)


def test_build_pack_handover_never_sets_flow(project: Path):
    """Requirement 5: handover mode never sets ``flow``."""
    orch = Orchestrator(project_root=project)
    pack = orch.build_pack(mode="handover", query="owner session")
    assert all(i.flow is None for i in pack.selected_items)


def test_build_pack_minimal_never_sets_flow(project: Path):
    """Requirement 5: minimal mode never sets ``flow``."""
    orch = Orchestrator(project_root=project)
    pack = orch.build_pack(mode="minimal", query="owner")
    assert all(i.flow is None for i in pack.selected_items)


def test_build_pack_debug_empty_graph_has_metadata_note(tmp_path: Path):
    """Requirement 4: empty graph in debug mode drops a ``note`` in metadata."""
    (tmp_path / ".context-router").mkdir()
    db_path = tmp_path / ".context-router" / "context-router.db"
    # Create DB with one symbol so the ranker has something to return, but
    # no ``calls`` edges -> each entry is a trivial self-loop flow.
    with Database(db_path) as db:
        sym_repo = SymbolRepository(db.connection)
        # Add a single leaf that is NOT a function/method -> not considered
        # an entry, so list_flows returns [].
        sym_repo.add(_mk_symbol("Config", "class", "/app/config.py"), "default")

    orch = Orchestrator(project_root=tmp_path)
    pack = orch.build_pack(mode="debug", query="config crash")
    assert all(i.flow is None for i in pack.selected_items)
    # The note may be either "no flows detected" (truly empty) or the
    # threshold message — both are acceptable non-empty explanations.
    assert pack.metadata.get("note")
