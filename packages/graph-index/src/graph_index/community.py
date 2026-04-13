"""Connected-components community detection for the symbol graph.

Uses a Union-Find (disjoint-set) algorithm over symbol edges to group
symbols into communities.  Each symbol is assigned a ``community_id``
that equals the canonical representative of its component.
"""

from __future__ import annotations

from storage_sqlite.repositories import EdgeRepository, SymbolRepository


# ---------------------------------------------------------------------------
# Union-Find (path-compressed, union-by-rank)
# ---------------------------------------------------------------------------

class _UnionFind:
    """Simple Union-Find with path compression and union-by-rank."""

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}
        self._rank: dict[int, int] = {}

    def find(self, x: int) -> int:
        """Return the canonical representative of x's component."""
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])  # path compression
        return self._parent[x]

    def union(self, x: int, y: int) -> None:
        """Merge the components containing x and y."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def ensure(self, x: int) -> None:
        """Ensure x is registered in the structure without merging."""
        self.find(x)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_communities(
    repo: str,
    sym_repo: SymbolRepository,
    edge_repo: EdgeRepository,
) -> int:
    """Assign community_id to every symbol using connected-components.

    Community ids are assigned as the canonical Union-Find root for each
    component, then re-labelled to dense consecutive integers (0, 1, 2 …).

    Args:
        repo: Repository identifier.
        sym_repo: SymbolRepository for reading symbols and writing community ids.
        edge_repo: EdgeRepository for reading edges.

    Returns:
        Number of distinct communities found.
    """
    all_symbols = sym_repo.get_all(repo)
    if not all_symbols:
        return 0

    # Build mapping from symbol name to db id for all symbols in this repo
    sym_ids: list[int] = []
    for sym in all_symbols:
        sid = sym_repo.get_id(repo, str(sym.file), sym.name, sym.kind)
        if sid is not None:
            sym_ids.append(sid)

    uf = _UnionFind()
    for sid in sym_ids:
        uf.ensure(sid)

    # Union all connected pairs
    for from_id, to_id in edge_repo.get_all_edges(repo):
        uf.union(from_id, to_id)

    # Re-label roots to dense community ids
    root_to_community: dict[int, int] = {}
    next_community = 0
    for sid in sym_ids:
        root = uf.find(sid)
        if root not in root_to_community:
            root_to_community[root] = next_community
            next_community += 1
        sym_repo.update_community(repo, sid, root_to_community[root])

    return next_community
