"""Flow detection over the persisted ``calls`` edge graph.

A *flow* is a BFS-discovered path from an **entry symbol** (e.g. an HTTP
handler, a ``main`` function, a test method) to a **leaf symbol** (the final
callee in the chain) along ``calls`` edges.  This module adds code-review-graph
parity for ``list_flows`` / ``get_affected_flows`` without requiring language
analyzers to emit flow metadata themselves — we re-use the existing symbol
and edge tables.

Design notes
------------
* Entry heuristics are intentionally modest and language-agnostic:
    - Name starts with ``test_`` (pytest / unittest style).
    - Name equals ``main`` (Python / Java / C#).
    - Name starts with an HTTP verb (``get``, ``post``, ``put``, ``delete``,
      ``patch``) followed by an underscore or a capital letter — catches
      controller methods like ``get_owner`` or ``getOwner``.
    - The symbol has **no incoming ``calls`` edges** in this repo (i.e. it
      is a root of the call graph). This naturally catches handler methods
      whose callers live in the framework (Spring / Flask / Express).
* Leaves are discovered lazily during BFS: a frontier node with no outgoing
  ``calls`` edges terminates the flow.
* Safety bounds (hard-coded, not configurable) keep pathological graphs in
  check: ``MAX_DEPTH = 10`` hops, ``MAX_FLOWS_PER_ENTRY = 50`` flows, and
  ``MAX_TOTAL_FLOWS = 5_000`` across all entries. Callers MUST NOT depend on
  the returned set being exhaustive.
* Silent-failure rule: if the database is malformed or a query raises, the
  public functions return ``[]`` rather than propagate — flow annotation is
  additive / advisory, never load-bearing.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from storage_sqlite.repositories import EdgeRepository, SymbolRepository

MAX_DEPTH = 10
MAX_FLOWS_PER_ENTRY = 50
MAX_TOTAL_FLOWS = 5_000

_HTTP_VERBS = ("get", "post", "put", "delete", "patch", "head", "options")


@dataclass(frozen=True)
class Flow:
    """A single discovered flow from an entry symbol to a leaf symbol.

    Attributes:
        entry_id: symbol id of the entry point.
        entry_name: name of the entry symbol (for display).
        leaf_id: symbol id of the terminal callee.
        leaf_name: name of the leaf symbol (for display).
        path: ordered list of symbol ids from entry to leaf inclusive.
        length: number of hops (``len(path) - 1``). 0 for self-contained
            entries that have no outgoing ``calls`` edges.
    """

    entry_id: int
    entry_name: str
    leaf_id: int
    leaf_name: str
    path: tuple[int, ...]
    length: int

    @property
    def label(self) -> str:
        """Return a compact human-readable label ``entry -> leaf``."""
        if self.entry_id == self.leaf_id:
            return self.entry_name
        return f"{self.entry_name} -> {self.leaf_name}"


def _is_entry_by_name(name: str) -> bool:
    """Return True when *name* looks like a flow entry by naming convention."""
    if not name:
        return False
    lower = name.lower()
    if lower == "main" or lower.startswith("test_") or lower.startswith("test"):
        # "test" prefix catches pytest's ``test_foo`` and JUnit's ``testFoo``.
        if lower == "test":
            return False  # plain "test" is ambiguous
        if lower.startswith("test_") or (
            lower.startswith("test") and len(name) > 4 and name[4].isupper()
        ):
            return True
        if lower == "main":
            return True
    if lower == "main":
        return True
    for verb in _HTTP_VERBS:
        if lower.startswith(verb + "_"):
            return True
        # camelCase variant: "getOwner", "postFoo" — verb then UPPER letter.
        if (
            lower.startswith(verb)
            and len(name) > len(verb)
            and name[len(verb)].isupper()
        ):
            return True
    return False


def _collect_entries(
    repo: str,
    sym_repo: SymbolRepository,
    edge_repo: EdgeRepository,
) -> list[tuple[int, str]]:
    """Return ``[(symbol_id, name), ...]`` for every detected entry symbol.

    A symbol is considered an entry when:
      * its name matches one of the heuristics in :func:`_is_entry_by_name`, **or**
      * it has no incoming ``calls`` edges (root-of-call-graph).
    Symbols without an outgoing edge **and** without a heuristic name match
    are excluded — they cannot produce a non-trivial flow and would just
    clutter the result.
    """
    try:
        all_symbols = sym_repo.get_all(repo)
    except Exception as exc:  # noqa: BLE001 — silent-failure contract
        print(
            f"warning: flows.list_flows: unable to load symbols for repo={repo!r}: {exc}",
            file=sys.stderr,
        )
        return []

    # Build an index of all callee symbol ids (i.e. those that appear as the
    # TO side of at least one ``calls`` edge). Anything NOT in this set is a
    # root of the call graph.
    try:
        conn = edge_repo._conn  # intentional: repository is a thin wrapper
        rows = conn.execute(
            "SELECT DISTINCT to_symbol_id FROM edges WHERE repo = ? AND edge_type = 'calls'",
            (repo,),
        ).fetchall()
        callee_ids = {r[0] for r in rows}
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: flows.list_flows: edge lookup failed for repo={repo!r}: {exc}",
            file=sys.stderr,
        )
        callee_ids = set()

    entries: list[tuple[int, str]] = []
    for sym in all_symbols:
        if sym.id is None or sym.kind not in ("function", "method"):
            continue
        name_match = _is_entry_by_name(sym.name)
        is_root = sym.id not in callee_ids
        if name_match or is_root:
            entries.append((sym.id, sym.name))
    return entries


def _callees(
    conn,
    repo: str,
    from_id: int,
) -> list[int]:
    """Return the list of direct callees for *from_id* via ``calls`` edges."""
    rows = conn.execute(
        "SELECT to_symbol_id FROM edges "
        "WHERE repo = ? AND from_symbol_id = ? AND edge_type = 'calls'",
        (repo, from_id),
    ).fetchall()
    return [r[0] for r in rows]


def _bfs_flows_from(
    conn,
    repo: str,
    entry_id: int,
    entry_name: str,
    id_to_name: dict[int, str],
) -> list[Flow]:
    """Return up to ``MAX_FLOWS_PER_ENTRY`` flows rooted at *entry_id*.

    A flow terminates at the first callee without outgoing ``calls`` edges,
    at ``MAX_DEPTH`` hops, or when a cycle is detected (the repeated symbol
    becomes the leaf). Each (entry, leaf) pair is reported at most once.
    """
    # BFS frontier of (path_tuple,) where path_tuple is the ordered list of
    # symbol ids visited from entry to current node inclusive.
    frontier: list[tuple[int, ...]] = [(entry_id,)]
    flows: list[Flow] = []
    seen_leaves: set[int] = set()

    while frontier and len(flows) < MAX_FLOWS_PER_ENTRY:
        next_frontier: list[tuple[int, ...]] = []
        for path in frontier:
            tail = path[-1]
            depth = len(path) - 1
            try:
                children = _callees(conn, repo, tail)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"warning: flows._bfs_flows_from: callee lookup failed at "
                    f"symbol_id={tail} in repo={repo!r}: {exc}",
                    file=sys.stderr,
                )
                children = []

            if not children or depth >= MAX_DEPTH:
                # Emit a flow only once per (entry, leaf) pair.
                if tail not in seen_leaves:
                    seen_leaves.add(tail)
                    flows.append(
                        Flow(
                            entry_id=entry_id,
                            entry_name=entry_name,
                            leaf_id=tail,
                            leaf_name=id_to_name.get(tail, str(tail)),
                            path=path,
                            length=depth,
                        )
                    )
                    if len(flows) >= MAX_FLOWS_PER_ENTRY:
                        break
                continue

            for child in children:
                if child in path:
                    # Cycle — treat the repeated symbol as the leaf.
                    if tail not in seen_leaves:
                        seen_leaves.add(tail)
                        flows.append(
                            Flow(
                                entry_id=entry_id,
                                entry_name=entry_name,
                                leaf_id=tail,
                                leaf_name=id_to_name.get(tail, str(tail)),
                                path=path,
                                length=depth,
                            )
                        )
                        if len(flows) >= MAX_FLOWS_PER_ENTRY:
                            break
                    continue
                next_frontier.append(path + (child,))
        frontier = next_frontier

    return flows


def list_flows(
    repo: str,
    sym_repo: SymbolRepository,
    edge_repo: EdgeRepository,
) -> list[Flow]:
    """Enumerate every flow in *repo* — entry symbol to leaf along ``calls``.

    Args:
        repo: Logical repository name.
        sym_repo: SymbolRepository bound to the same connection as *edge_repo*.
        edge_repo: EdgeRepository used for call-edge traversal.

    Returns:
        List of :class:`Flow` objects, capped at ``MAX_TOTAL_FLOWS``. Never
        raises; on error returns ``[]`` and writes a warning to stderr.
    """
    try:
        entries = _collect_entries(repo, sym_repo, edge_repo)
        if not entries:
            return []

        # Pre-build id -> name lookup for cheap leaf labelling.
        try:
            all_syms = sym_repo.get_all(repo)
        except Exception as exc:  # noqa: BLE001
            print(
                f"warning: flows.list_flows: unable to load symbols (phase 2) "
                f"for repo={repo!r}: {exc}",
                file=sys.stderr,
            )
            return []
        id_to_name: dict[int, str] = {
            s.id: s.name for s in all_syms if s.id is not None
        }

        conn = edge_repo._conn
        flows: list[Flow] = []
        for entry_id, entry_name in entries:
            if len(flows) >= MAX_TOTAL_FLOWS:
                break
            flows.extend(
                _bfs_flows_from(conn, repo, entry_id, entry_name, id_to_name)
            )
        return flows[:MAX_TOTAL_FLOWS]
    except Exception as exc:  # noqa: BLE001 — silent-failure contract
        print(
            f"warning: flows.list_flows: unexpected failure for repo={repo!r}: {exc}",
            file=sys.stderr,
        )
        return []


def get_affected_flows(
    repo: str,
    sym_repo: SymbolRepository,
    edge_repo: EdgeRepository,
    symbol_id: int,
) -> list[Flow]:
    """Return every flow whose path contains *symbol_id*.

    Handy for debug-mode annotation: given a symbol extracted from a ranked
    pack item, this returns the flows (entry -> leaf) it participates in so
    the caller can tag the item with a human-readable flow label.

    Args:
        repo: Logical repository name.
        sym_repo: SymbolRepository bound to the same connection as *edge_repo*.
        edge_repo: EdgeRepository used for call-edge traversal.
        symbol_id: Symbol id to look up.

    Returns:
        List of :class:`Flow` objects (possibly empty). Never raises.
    """
    try:
        all_flows = list_flows(repo, sym_repo, edge_repo)
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: flows.get_affected_flows: list_flows failed for "
            f"repo={repo!r}, symbol_id={symbol_id}: {exc}",
            file=sys.stderr,
        )
        return []
    return [f for f in all_flows if symbol_id in f.path]
