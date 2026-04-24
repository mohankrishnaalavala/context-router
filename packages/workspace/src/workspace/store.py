"""SQLite-backed workspace store — persists repo registrations and cross-repo edges."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RepoRecord:
    """Minimal record for a registered repo in the workspace DB."""

    repo_id: str
    name: str
    root: str


@dataclass
class CrossRepoEdge:
    """A directed dependency edge between two repos."""

    src_repo_id: str
    src_file: str
    dst_repo_id: str
    dst_file: str
    edge_kind: str
    confidence: float
    src_symbol_id: str | None = field(default=None)
    dst_symbol_id: str | None = field(default=None)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    repo_id   TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    root      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cross_repo_edges (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    src_repo_id   TEXT NOT NULL,
    src_symbol_id TEXT,
    src_file      TEXT NOT NULL,
    dst_repo_id   TEXT NOT NULL,
    dst_symbol_id TEXT,
    dst_file      TEXT NOT NULL,
    edge_kind     TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_edges_src
    ON cross_repo_edges (src_repo_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst
    ON cross_repo_edges (dst_repo_id);
"""


def open_workspace_db(db_path: Path) -> sqlite3.Connection:
    """Open (or create) the workspace SQLite DB and apply the schema.

    Args:
        db_path: Path to the ``workspace.db`` file.  Parent directory is
            created automatically.

    Returns:
        An open ``sqlite3.Connection`` with WAL mode enabled.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(_SCHEMA)
    con.commit()
    return con


# ---------------------------------------------------------------------------
# WorkspaceStore
# ---------------------------------------------------------------------------

class WorkspaceStore:
    """Manages repo registrations and cross-repo edges in a SQLite database.

    Use the class method :meth:`open` to obtain an instance.  Call
    :meth:`close` (or use as a context manager) when done.
    """

    def __init__(self, con: sqlite3.Connection) -> None:
        self._con = con

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, db_path: Path) -> "WorkspaceStore":
        """Open or create a workspace DB at *db_path*.

        Args:
            db_path: Filesystem path to the SQLite file.

        Returns:
            A ready :class:`WorkspaceStore` instance.
        """
        return cls(open_workspace_db(db_path))

    def close(self) -> None:
        """Close the underlying database connection."""
        self._con.close()

    def __enter__(self) -> "WorkspaceStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Repo registration
    # ------------------------------------------------------------------

    def register_repo(self, repo: RepoRecord) -> None:
        """Insert or replace a repo record.

        Args:
            repo: The :class:`RepoRecord` to upsert.
        """
        self._con.execute(
            "INSERT OR REPLACE INTO repos (repo_id, name, root) VALUES (?, ?, ?)",
            (repo.repo_id, repo.name, repo.root),
        )
        self._con.commit()

    def list_repos(self) -> list[RepoRecord]:
        """Return all registered repos."""
        rows = self._con.execute(
            "SELECT repo_id, name, root FROM repos ORDER BY name"
        ).fetchall()
        return [RepoRecord(repo_id=r[0], name=r[1], root=r[2]) for r in rows]

    # ------------------------------------------------------------------
    # Edge management
    # ------------------------------------------------------------------

    def replace_edges_for_src(
        self, src_repo_id: str, edges: list[CrossRepoEdge]
    ) -> int:
        """Replace all edges sourced from *src_repo_id* with *edges*.

        Idempotent: calling twice with the same edges yields the same DB
        state.  The count returned is the number of distinct
        ``(src_file, dst_repo_id, dst_file, edge_kind)`` combinations
        stored after the replacement.

        Args:
            src_repo_id: The source repo whose edges are replaced.
            edges: New edge list (may be empty to clear all edges).

        Returns:
            Count of unique edges written.
        """
        # De-duplicate on the logical key before inserting.
        seen: set[tuple[str, str, str, str]] = set()
        deduped: list[CrossRepoEdge] = []
        for e in edges:
            key = (e.src_file, e.dst_repo_id, e.dst_file, e.edge_kind)
            if key not in seen:
                seen.add(key)
                deduped.append(e)

        with self._con:
            self._con.execute(
                "DELETE FROM cross_repo_edges WHERE src_repo_id = ?",
                (src_repo_id,),
            )
            self._con.executemany(
                """
                INSERT INTO cross_repo_edges
                    (src_repo_id, src_symbol_id, src_file,
                     dst_repo_id, dst_symbol_id, dst_file,
                     edge_kind, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        e.src_repo_id,
                        e.src_symbol_id,
                        e.src_file,
                        e.dst_repo_id,
                        e.dst_symbol_id,
                        e.dst_file,
                        e.edge_kind,
                        e.confidence,
                    )
                    for e in deduped
                ],
            )
        return len(deduped)

    def edges_from(self, src_repo_id: str) -> Iterator[CrossRepoEdge]:
        """Yield all edges sourced from *src_repo_id*.

        Args:
            src_repo_id: The source repo ID to query.

        Yields:
            :class:`CrossRepoEdge` instances.
        """
        rows = self._con.execute(
            """
            SELECT src_repo_id, src_symbol_id, src_file,
                   dst_repo_id, dst_symbol_id, dst_file,
                   edge_kind, confidence
            FROM cross_repo_edges
            WHERE src_repo_id = ?
            ORDER BY src_file, dst_repo_id, dst_file
            """,
            (src_repo_id,),
        ).fetchall()
        for r in rows:
            yield CrossRepoEdge(
                src_repo_id=r[0],
                src_symbol_id=r[1],
                src_file=r[2],
                dst_repo_id=r[3],
                dst_symbol_id=r[4],
                dst_file=r[5],
                edge_kind=r[6],
                confidence=r[7],
            )
