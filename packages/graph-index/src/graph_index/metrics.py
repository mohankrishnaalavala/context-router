"""Structural metrics for the symbol graph: hub and bridge scores.

These scores are cheap, additive signals used by the ranker to lift
symbols that are structurally central (many inbound references) or act
as bridges between communities (outbound edges crossing community
boundaries). Both scores are normalised to the [0, 1] range so the
ranker can combine them with its existing BM25 + semantic signals.

Design constraints (see the ``hub-bridge-ranking-signals`` outcome):

* Hub: inbound-degree normalised by the repo max. Linear-scan SQL; no
  eigenvector / PageRank.
* Bridge: count of DISTINCT destination communities for each source
  symbol, normalised by the repo max. Approximates betweenness at a
  fraction of the cost.
* Silent-failure rule: if the connection is ``None`` or a required
  table is missing, the function returns ``{}`` and logs a one-line
  debug note to stderr. Callers (the ranker) skip the boost gracefully.
"""

from __future__ import annotations

import sqlite3
import sys
from typing import Any

# Edge kinds that contribute to the hub / bridge signal. ``calls`` and
# ``imports`` are the two general-purpose kinds; ``extends`` and
# ``implements`` from #48 give inheritance-heavy hubs (e.g. base
# classes, interfaces) the weight they deserve.
_HUB_EDGE_KINDS: tuple[str, ...] = ("calls", "imports", "extends", "implements")
_BRIDGE_EDGE_KINDS: tuple[str, ...] = ("calls", "imports")


def _debug(msg: str) -> None:
    """Emit a one-line stderr note. Best-effort; never raises."""
    try:
        print(f"context-router[metrics]: {msg}", file=sys.stderr)
    except Exception:  # noqa: BLE001 — logging must never break ranking
        pass


def compute_hub_scores(
    db_connection: Any, repo: str
) -> dict[int, float]:
    """Return ``{symbol_id: hub_score}`` where scores are in ``[0, 1]``.

    Hub score = inbound degree (across calls / imports / extends /
    implements) normalised by the repo maximum. A symbol with 0 inbound
    edges is simply absent from the result (callers default to 0.0).

    Args:
        db_connection: Open ``sqlite3.Connection`` for the project DB.
            May be ``None`` — returns ``{}`` in that case.
        repo: Repository identifier to scope the query (typically
            ``"default"`` for single-repo indexing).

    Returns:
        Mapping of symbol id to hub score. Empty dict on any failure.
    """
    if db_connection is None:
        _debug("hub: db_connection is None; returning {}")
        return {}

    placeholders = ",".join("?" for _ in _HUB_EDGE_KINDS)
    query = (
        "SELECT to_symbol_id, COUNT(*) "
        "FROM edges "
        f"WHERE repo = ? AND edge_type IN ({placeholders}) "
        "  AND to_symbol_id IS NOT NULL "
        "GROUP BY to_symbol_id"
    )

    try:
        rows = db_connection.execute(
            query, (repo, *_HUB_EDGE_KINDS)
        ).fetchall()
    except sqlite3.Error as exc:
        _debug(f"hub: query failed ({type(exc).__name__}: {exc}); returning {{}}")
        return {}

    if not rows:
        return {}

    # sqlite3.Row / tuple both index-accessible with [0] and [1].
    degrees: list[tuple[int, int]] = [(int(r[0]), int(r[1])) for r in rows]
    max_deg = max(d for _, d in degrees)
    if max_deg <= 0:
        return {}
    return {sid: deg / max_deg for sid, deg in degrees}


def compute_bridge_scores(
    db_connection: Any, repo: str
) -> dict[int, float]:
    """Return ``{symbol_id: bridge_score}`` where scores are in ``[0, 1]``.

    Bridge score approximates betweenness as the number of DISTINCT
    destination communities a symbol's outbound calls / imports reach,
    normalised by the repo maximum. Symbols that only touch one
    community are not bridges and are excluded from the result (callers
    default to 0.0).

    Requires ``symbols.community_id`` to be populated — the caller
    (typically the orchestrator via the indexer) owns that pass.

    Args:
        db_connection: Open ``sqlite3.Connection`` for the project DB.
            May be ``None`` — returns ``{}`` in that case.
        repo: Repository identifier to scope the query.

    Returns:
        Mapping of symbol id to bridge score. Empty dict on any failure
        or if no symbol crosses a community boundary.
    """
    if db_connection is None:
        _debug("bridge: db_connection is None; returning {}")
        return {}

    placeholders = ",".join("?" for _ in _BRIDGE_EDGE_KINDS)
    # Count DISTINCT destination communities per source symbol.
    # HAVING > 1 filters out intra-community symbols (score would be 0).
    query = (
        "SELECT s.id, COUNT(DISTINCT t.community_id) "
        "FROM symbols s "
        "JOIN edges e ON e.from_symbol_id = s.id AND e.repo = s.repo "
        "JOIN symbols t ON t.id = e.to_symbol_id AND t.repo = s.repo "
        "WHERE s.repo = ? "
        f"  AND e.edge_type IN ({placeholders}) "
        "  AND t.community_id IS NOT NULL "
        "GROUP BY s.id "
        "HAVING COUNT(DISTINCT t.community_id) > 1"
    )

    try:
        rows = db_connection.execute(
            query, (repo, *_BRIDGE_EDGE_KINDS)
        ).fetchall()
    except sqlite3.Error as exc:
        _debug(
            f"bridge: query failed ({type(exc).__name__}: {exc}); returning {{}}"
        )
        return {}

    if not rows:
        return {}

    crossings: list[tuple[int, int]] = [(int(r[0]), int(r[1])) for r in rows]
    max_cross = max(c for _, c in crossings)
    if max_cross <= 0:
        return {}
    return {sid: cross / max_cross for sid, cross in crossings}


__all__ = ["compute_hub_scores", "compute_bridge_scores"]
