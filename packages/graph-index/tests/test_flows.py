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


# ---------------------------------------------------------------------------
# N+1 fix — _FlowCache memoizes callee lookups per public call
# ---------------------------------------------------------------------------


class _CountingConn:
    """Wrap a real sqlite3 connection and count every ``execute`` call.

    Used to assert that a ``list_flows`` run hits the database at most once
    per distinct symbol id (plus a handful of fixed queries for
    ``_collect_entries`` and ``sym_repo.get_all``).
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.call_count = 0
        self.call_sids: list[int] = []

    def execute(self, sql, params=(), *args, **kwargs):
        self.call_count += 1
        # Record the symbol id argument for callee lookups so we can assert
        # uniqueness. The callee query always has (repo, sid) params.
        if "from_symbol_id" in sql and len(params) >= 2:
            self.call_sids.append(params[1])
        return self._inner.execute(sql, params, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_flow_cache_memoizes_callees_single_query_per_sid(repos, db):
    """A ``_FlowCache`` must issue at most one SQL query per distinct sid.

    This is the core N+1 guarantee: a BFS that visits the same symbol through
    different paths doesn't re-fetch its callees.
    """
    from graph_index.flows import _FlowCache

    sym_repo, edge_repo = repos
    repo = "r"

    a = sym_repo.add(_mk("entry_a", "function", "/a.py"), repo)
    b = sym_repo.add(_mk("entry_b", "function", "/b.py"), repo)
    leaf = sym_repo.add(_mk("shared_leaf", "function", "/l.py"), repo)
    edge_repo.add_raw(repo, a, leaf, "calls")
    edge_repo.add_raw(repo, b, leaf, "calls")

    counting = _CountingConn(db.connection)
    cache = _FlowCache(counting, repo)

    # First call — cold, should issue one query.
    assert cache.callees(a) == [leaf]
    assert counting.call_count == 1
    # Second call, same sid — must be served from cache.
    assert cache.callees(a) == [leaf]
    assert counting.call_count == 1
    # Different sid — one more query.
    assert cache.callees(b) == [leaf]
    assert counting.call_count == 2
    # Leaf has no callees — still memoized after first miss.
    assert cache.callees(leaf) == []
    assert cache.callees(leaf) == []
    assert counting.call_count == 3
    # Each sid appeared at most once in the SQL param log.
    assert sorted(counting.call_sids) == sorted([a, b, leaf])


def test_list_flows_does_not_issue_n_plus_one_queries(repos, db):
    """Regression: ``list_flows`` issues O(distinct symbols) callee queries.

    Construct a diamond graph where two entries share a common descendant.
    Without the cache, BFS would query the shared subtree once per entry.
    With the cache, each symbol's callees are looked up exactly once.
    """
    sym_repo, edge_repo = repos
    repo = "r"

    # Two entries converging on a shared mid -> leaf chain.
    e1 = sym_repo.add(_mk("get_one", "function", "/ctrl.py"), repo)
    e2 = sym_repo.add(_mk("get_two", "function", "/ctrl.py"), repo)
    mid = sym_repo.add(_mk("find", "method", "/svc.py"), repo)
    leaf = sym_repo.add(_mk("select", "method", "/db.py"), repo)
    edge_repo.add_raw(repo, e1, mid, "calls")
    edge_repo.add_raw(repo, e2, mid, "calls")
    edge_repo.add_raw(repo, mid, leaf, "calls")

    # Monkey-patch EdgeRepository._conn to a counting wrapper so both
    # _collect_entries and _bfs_flows_from see it.
    counting = _CountingConn(db.connection)
    edge_repo._conn = counting

    flows = list_flows(repo, sym_repo, edge_repo)

    # Correctness: two flows (one per entry), both end at leaf.
    assert {f.entry_id for f in flows} == {e1, e2}
    assert all(f.leaf_id == leaf for f in flows)

    # Callee-lookup invariant: every sid we queried callees for appears
    # at most once, i.e. the cache caught all re-visits.
    from collections import Counter

    sid_counts = Counter(counting.call_sids)
    assert all(n == 1 for n in sid_counts.values()), (
        f"_callees lookup repeated for some symbol(s): {sid_counts}"
    )
    # Total callee queries are bounded by distinct traversed symbols (4).
    assert len(counting.call_sids) <= 4


def test_get_affected_flows_shares_cache_across_entries(repos, db):
    """``get_affected_flows`` delegates to ``list_flows`` and must benefit
    from the same per-call cache — no duplicate callee queries."""
    sym_repo, edge_repo = repos
    repo = "r"

    e1 = sym_repo.add(_mk("get_a", "function", "/ctrl.py"), repo)
    e2 = sym_repo.add(_mk("get_b", "function", "/ctrl.py"), repo)
    shared = sym_repo.add(_mk("find", "method", "/svc.py"), repo)
    edge_repo.add_raw(repo, e1, shared, "calls")
    edge_repo.add_raw(repo, e2, shared, "calls")

    counting = _CountingConn(db.connection)
    edge_repo._conn = counting

    flows = get_affected_flows(repo, sym_repo, edge_repo, shared)
    assert len(flows) == 2  # both entries reach `shared`
    from collections import Counter

    sid_counts = Counter(counting.call_sids)
    assert all(n == 1 for n in sid_counts.values()), (
        f"get_affected_flows caused duplicate callee queries: {sid_counts}"
    )


def test_list_flows_on_empty_graph_issues_zero_callee_queries(repos, db):
    """No symbols => no callee queries, no crash. Matches the sentinel spec
    (empty graph in the N+1 check)."""
    sym_repo, edge_repo = repos
    counting = _CountingConn(db.connection)
    edge_repo._conn = counting

    assert list_flows("r", sym_repo, edge_repo) == []
    # No from_symbol_id queries were needed at all.
    assert counting.call_sids == []


def test_flow_cache_swallows_lookup_exceptions(repos, db):
    """A SQL failure on one sid must not prevent later cached lookups."""
    from graph_index.flows import _FlowCache

    class _FlakyConn:
        def __init__(self, inner):
            self._inner = inner
            self.bad_sid = None

        def execute(self, sql, params=(), *args, **kwargs):
            if self.bad_sid is not None and len(params) >= 2 and params[1] == self.bad_sid:
                raise RuntimeError("simulated sqlite failure")
            return self._inner.execute(sql, params, *args, **kwargs)

    sym_repo, edge_repo = repos
    repo = "r"
    a = sym_repo.add(_mk("a", "function", "/a.py"), repo)
    b = sym_repo.add(_mk("b", "function", "/b.py"), repo)
    edge_repo.add_raw(repo, a, b, "calls")

    flaky = _FlakyConn(db.connection)
    flaky.bad_sid = a
    cache = _FlowCache(flaky, repo)
    # First call — exception is caught, returns [] and is memoized.
    assert cache.callees(a) == []
    assert cache.exc_count == 1
    # Second call — served from cache, no further exception.
    assert cache.callees(a) == []
    assert cache.exc_count == 1
    # Different sid — still works.
    flaky.bad_sid = None  # stop flaking
    assert cache.callees(b) == []  # b has no callees
    assert cache.exc_count == 1
