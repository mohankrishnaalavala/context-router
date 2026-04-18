"""Tests for the graph_index.flows module.

Covers the five Phase 4 Wave 1 requirements:
  1. list_flows returns correct entry -> leaf paths for a small engineered graph.
  2. get_affected_flows on a mid-path symbol returns only passing-through flows.
  3. Empty graph: list_flows returns [].
  4. Cycle handling: BFS terminates and reports the revisited node as the leaf.
  5. Bounds: MAX_DEPTH stops runaway paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.interfaces import Symbol
from graph_index.flows import (
    MAX_DEPTH,
    Flow,
    _is_entry_by_name,
    get_affected_flows,
    list_flows,
)
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


@pytest.fixture()
def db(tmp_path: Path):
    """Provide a fresh SQLite database for each test."""
    db = Database(tmp_path / "flows.db")
    db.initialize()
    yield db
    db.close()


@pytest.fixture()
def repos(db):
    """Provide SymbolRepository and EdgeRepository sharing the same connection."""
    conn = db.connection
    return SymbolRepository(conn), EdgeRepository(conn)


def _mk(name: str, kind: str, file_path: str) -> Symbol:
    return Symbol(
        name=name,
        kind=kind,
        file=Path(file_path),
        line_start=1,
        line_end=5,
        language="python",
    )


# ---------------------------------------------------------------------------
# Entry-name heuristics
# ---------------------------------------------------------------------------


def test_is_entry_by_name_covers_expected_patterns():
    """Name heuristic matches pytest, main, and HTTP verb prefixes."""
    for n in ("test_foo", "testFoo", "main", "get_owner", "getOwner", "postItem"):
        assert _is_entry_by_name(n), n
    for n in ("", "helper", "compute", "run", "tester", "gettings"):
        assert not _is_entry_by_name(n), n


# ---------------------------------------------------------------------------
# list_flows
# ---------------------------------------------------------------------------


def test_list_flows_on_empty_graph_returns_empty(repos):
    """Requirement 3: empty graph -> list_flows returns []."""
    sym_repo, edge_repo = repos
    assert list_flows("r", sym_repo, edge_repo) == []


def test_list_flows_returns_entry_leaf_paths(repos):
    """Requirement 1: engineered graph with one entry -> mid -> leaf."""
    sym_repo, edge_repo = repos
    repo = "r"

    # Entry has a recognized name ("get_owner"); mid and leaf are not roots.
    entry_id = sym_repo.add(_mk("get_owner", "function", "/src/ctrl.py"), repo)
    mid_id = sym_repo.add(_mk("find_owner", "method", "/src/svc.py"), repo)
    leaf_id = sym_repo.add(_mk("select_by_id", "method", "/src/db.py"), repo)

    edge_repo.add_raw(repo, entry_id, mid_id, "calls")
    edge_repo.add_raw(repo, mid_id, leaf_id, "calls")

    flows = list_flows(repo, sym_repo, edge_repo)

    assert len(flows) == 1
    f = flows[0]
    assert f.entry_id == entry_id
    assert f.entry_name == "get_owner"
    assert f.leaf_id == leaf_id
    assert f.leaf_name == "select_by_id"
    assert f.path == (entry_id, mid_id, leaf_id)
    assert f.length == 2
    assert f.label == "get_owner -> select_by_id"


def test_list_flows_root_without_heuristic_is_still_entry(repos):
    """A function with no incoming ``calls`` edges becomes an entry even when
    its name does not match the HTTP/main/test heuristics."""
    sym_repo, edge_repo = repos
    repo = "r"

    # "handler" is neither HTTP-prefixed nor test/main, but has no callers.
    handler_id = sym_repo.add(_mk("handler", "function", "/src/h.py"), repo)
    leaf_id = sym_repo.add(_mk("do_work", "function", "/src/w.py"), repo)
    edge_repo.add_raw(repo, handler_id, leaf_id, "calls")

    flows = list_flows(repo, sym_repo, edge_repo)
    assert len(flows) == 1
    assert flows[0].entry_id == handler_id
    assert flows[0].leaf_id == leaf_id


def test_list_flows_handles_cycles(repos):
    """Requirement 4: a cycle must not cause infinite BFS."""
    sym_repo, edge_repo = repos
    repo = "r"

    a_id = sym_repo.add(_mk("main", "function", "/src/a.py"), repo)
    b_id = sym_repo.add(_mk("b", "function", "/src/b.py"), repo)

    edge_repo.add_raw(repo, a_id, b_id, "calls")
    edge_repo.add_raw(repo, b_id, a_id, "calls")  # cycle back to main

    flows = list_flows(repo, sym_repo, edge_repo)

    # BFS terminates, reporting b as a leaf when the cycle closes.
    assert flows
    assert all(f.length <= MAX_DEPTH for f in flows)


def test_list_flows_respects_max_depth(repos):
    """Requirement 5: long chains are truncated at MAX_DEPTH."""
    sym_repo, edge_repo = repos
    repo = "r"

    # Chain of length MAX_DEPTH + 3 — list_flows must stop at MAX_DEPTH.
    ids = []
    for i in range(MAX_DEPTH + 3):
        sid = sym_repo.add(
            _mk(f"fn_{i}" if i > 0 else "main", "function", f"/src/f{i}.py"),
            repo,
        )
        ids.append(sid)
    for i in range(len(ids) - 1):
        edge_repo.add_raw(repo, ids[i], ids[i + 1], "calls")

    flows = list_flows(repo, sym_repo, edge_repo)
    # Exactly one entry (main); BFS terminates at MAX_DEPTH.
    assert len(flows) == 1
    assert flows[0].length == MAX_DEPTH


def test_list_flows_ignores_non_calls_edges(repos):
    """Flows only follow ``calls``; ``imports`` and ``tested_by`` are skipped."""
    sym_repo, edge_repo = repos
    repo = "r"

    a_id = sym_repo.add(_mk("get_it", "function", "/src/a.py"), repo)
    b_id = sym_repo.add(_mk("b", "function", "/src/b.py"), repo)
    edge_repo.add_raw(repo, a_id, b_id, "imports")

    flows = list_flows(repo, sym_repo, edge_repo)
    # Each ends up as its own flow (no calls edges to follow).
    assert len(flows) == 2
    assert all(f.length == 0 for f in flows)
    assert {f.leaf_name for f in flows} == {"get_it", "b"}


# ---------------------------------------------------------------------------
# get_affected_flows
# ---------------------------------------------------------------------------


def test_get_affected_flows_returns_only_passing_flows(repos):
    """Requirement 2: mid-path symbol returns the flow that contains it, not
    an unrelated flow."""
    sym_repo, edge_repo = repos
    repo = "r"

    # Flow 1: main -> a -> b
    m1 = sym_repo.add(_mk("main", "function", "/m1.py"), repo)
    a1 = sym_repo.add(_mk("a", "function", "/a1.py"), repo)
    b1 = sym_repo.add(_mk("b", "function", "/b1.py"), repo)
    edge_repo.add_raw(repo, m1, a1, "calls")
    edge_repo.add_raw(repo, a1, b1, "calls")

    # Flow 2: test_x -> c (unrelated)
    tx = sym_repo.add(_mk("test_x", "function", "/tests/t.py"), repo)
    c2 = sym_repo.add(_mk("c", "function", "/c.py"), repo)
    edge_repo.add_raw(repo, tx, c2, "calls")

    touching_a = get_affected_flows(repo, sym_repo, edge_repo, a1)
    assert len(touching_a) == 1
    assert touching_a[0].entry_id == m1
    assert touching_a[0].leaf_id == b1

    touching_c = get_affected_flows(repo, sym_repo, edge_repo, c2)
    assert len(touching_c) == 1
    assert touching_c[0].entry_id == tx


def test_get_affected_flows_unknown_symbol_returns_empty(repos):
    """Symbols not in any flow path return []."""
    sym_repo, edge_repo = repos
    repo = "r"

    m = sym_repo.add(_mk("main", "function", "/m.py"), repo)
    a = sym_repo.add(_mk("a", "function", "/a.py"), repo)
    edge_repo.add_raw(repo, m, a, "calls")

    # symbol_id 9999 does not exist — returns [].
    assert get_affected_flows(repo, sym_repo, edge_repo, 9999) == []


# ---------------------------------------------------------------------------
# Flow dataclass behaviour
# ---------------------------------------------------------------------------


def test_flow_label_self_contained_entry():
    """A flow with entry == leaf (no outgoing calls) labels as the entry name."""
    f = Flow(
        entry_id=1,
        entry_name="main",
        leaf_id=1,
        leaf_name="main",
        path=(1,),
        length=0,
    )
    assert f.label == "main"
