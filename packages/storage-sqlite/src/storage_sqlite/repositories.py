"""Repository classes for context-router's SQLite storage.

Each repository wraps a single domain entity and provides typed read/write
access. All SQL uses parameterized queries — never string interpolation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol
from contracts.models import Decision, Observation, RuntimeSignal


class ObservationRepository:
    """Typed access to the observations table and its FTS5 index."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection.

        Args:
            conn: An open sqlite3.Connection (caller owns lifetime).
        """
        self._conn = conn

    def add(self, obs: Observation) -> int:
        """Insert an observation and sync it into the FTS index.

        Args:
            obs: The Observation to persist.

        Returns:
            The rowid of the newly inserted row.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO observations
                (timestamp, task_type, summary, files_touched, commands_run,
                 failures_seen, fix_summary, commit_sha, repo_scope, task_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                obs.timestamp.isoformat(),
                obs.task_type,
                obs.summary,
                json.dumps(obs.files_touched),
                json.dumps(obs.commands_run),
                json.dumps(obs.failures_seen),
                obs.fix_summary,
                obs.commit_sha,
                obs.repo_scope,
                obs.task_hash,
            ),
        )
        rowid = cursor.lastrowid
        # Sync FTS5 content table
        self._conn.execute(
            "INSERT INTO observations_fts(rowid, summary, fix_summary) VALUES (?, ?, ?)",
            (rowid, obs.summary, obs.fix_summary),
        )
        self._conn.commit()
        return rowid  # type: ignore[return-value]

    def search_fts(self, query: str) -> list[Observation]:
        """Full-text search across summary and fix_summary fields.

        Args:
            query: FTS5 query string.

        Returns:
            List of matching Observation objects, most recently added first.
        """
        rows = self._conn.execute(
            """
            SELECT o.*
            FROM observations o
            JOIN observations_fts fts ON o.rowid = fts.rowid
            WHERE observations_fts MATCH ?
            ORDER BY o.rowid DESC
            """,
            (query,),
        ).fetchall()
        return [self._row_to_observation(r) for r in rows]

    def find_by_task_hash(self, task_hash: str) -> "Observation | None":
        """Return the first observation with the given task_hash, or None.

        Args:
            task_hash: Short SHA256 hash computed by the capture guardrail.

        Returns:
            Matching Observation or None if not found.
        """
        if not task_hash:
            return None
        row = self._conn.execute(
            "SELECT * FROM observations WHERE task_hash = ? LIMIT 1",
            (task_hash,),
        ).fetchone()
        return self._row_to_observation(row) if row else None

    def _row_to_observation(self, row: sqlite3.Row) -> Observation:
        """Convert a sqlite3.Row to an Observation model."""
        keys = row.keys() if hasattr(row, "keys") else []
        return Observation(
            timestamp=datetime.fromisoformat(row["timestamp"]),
            task_type=row["task_type"] or "",
            summary=row["summary"] or "",
            files_touched=json.loads(row["files_touched"] or "[]"),
            commands_run=json.loads(row["commands_run"] or "[]"),
            failures_seen=json.loads(row["failures_seen"] or "[]"),
            fix_summary=row["fix_summary"] or "",
            commit_sha=row["commit_sha"] or "",
            repo_scope=row["repo_scope"] or "",
            task_hash=row["task_hash"] if "task_hash" in keys else "",
        )


class DecisionRepository:
    """Typed access to the decisions table and its FTS5 index."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection."""
        self._conn = conn

    def add(self, dec: Decision) -> str:
        """Insert a decision and sync it into the FTS index.

        Args:
            dec: The Decision to persist.

        Returns:
            The UUID string of the inserted decision.
        """
        self._conn.execute(
            """
            INSERT INTO decisions
                (id, title, status, context, decision, consequences, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dec.id,
                dec.title,
                dec.status,
                dec.context,
                dec.decision,
                dec.consequences,
                json.dumps(dec.tags),
                dec.created_at.isoformat(),
            ),
        )
        # Fetch the implicit rowid for FTS sync
        row = self._conn.execute(
            "SELECT rowid FROM decisions WHERE id = ?", (dec.id,)
        ).fetchone()
        self._conn.execute(
            "INSERT INTO decisions_fts(rowid, title, context, decision) VALUES (?, ?, ?, ?)",
            (row["rowid"], dec.title, dec.context, dec.decision),
        )
        self._conn.commit()
        return dec.id

    def search_fts(self, query: str) -> list[Decision]:
        """Full-text search across title, context, and decision fields.

        Args:
            query: FTS5 query string.

        Returns:
            List of matching Decision objects.
        """
        rows = self._conn.execute(
            """
            SELECT d.*
            FROM decisions d
            JOIN decisions_fts fts ON d.rowid = fts.rowid
            WHERE decisions_fts MATCH ?
            ORDER BY d.created_at DESC
            """,
            (query,),
        ).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def _row_to_decision(self, row: sqlite3.Row) -> Decision:
        """Convert a sqlite3.Row to a Decision model."""
        return Decision(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            context=row["context"] or "",
            decision=row["decision"] or "",
            consequences=row["consequences"] or "",
            tags=json.loads(row["tags"] or "[]"),
            created_at=datetime.fromisoformat(row["created_at"]),
        )


class RuntimeSignalRepository:
    """Typed access to the runtime_signals table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection."""
        self._conn = conn

    def add(self, sig: RuntimeSignal) -> int:
        """Insert a runtime signal.

        Args:
            sig: The RuntimeSignal to persist.

        Returns:
            The rowid of the newly inserted row.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO runtime_signals
                (source, severity, message, stack, paths, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sig.source,
                sig.severity,
                sig.message,
                json.dumps(sig.stack),
                json.dumps([str(p) for p in sig.paths]),
                sig.timestamp.isoformat(),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


class SymbolRepository:
    """Typed access to the symbols table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection."""
        self._conn = conn

    def add(self, sym: Symbol, repo: str) -> int:
        """Insert a symbol row and return its rowid.

        Args:
            sym: The Symbol to persist.
            repo: Logical repository name (e.g. "default").

        Returns:
            The integer rowid of the inserted row.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO symbols
                (repo, file_path, name, kind, line_start, line_end,
                 language, signature, docstring)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                repo,
                str(sym.file),
                sym.name,
                sym.kind,
                sym.line_start,
                sym.line_end,
                sym.language,
                sym.signature,
                sym.docstring,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def add_bulk(self, syms: list[Symbol], repo: str) -> None:
        """Insert multiple symbols in a single transaction.

        Args:
            syms: List of Symbol objects to insert.
            repo: Logical repository name.
        """
        self._conn.executemany(
            """
            INSERT INTO symbols
                (repo, file_path, name, kind, line_start, line_end,
                 language, signature, docstring)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    repo,
                    str(s.file),
                    s.name,
                    s.kind,
                    s.line_start,
                    s.line_end,
                    s.language,
                    s.signature,
                    s.docstring,
                )
                for s in syms
            ],
        )
        self._conn.commit()

    def delete_by_file(self, repo: str, file_path: str) -> None:
        """Delete all symbols for a given file (used before incremental re-index).

        Args:
            repo: Logical repository name.
            file_path: Path string as stored in the DB.
        """
        self._conn.execute(
            "DELETE FROM symbols WHERE repo = ? AND file_path = ?",
            (repo, file_path),
        )
        self._conn.commit()

    def get_by_file(self, repo: str, file_path: str) -> list[Symbol]:
        """Return all symbols for a given file.

        Args:
            repo: Logical repository name.
            file_path: Path string as stored in the DB.

        Returns:
            List of Symbol dataclass instances.
        """
        rows = self._conn.execute(
            """
            SELECT name, kind, file_path, line_start, line_end,
                   language, signature, docstring
            FROM symbols
            WHERE repo = ? AND file_path = ?
            """,
            (repo, file_path),
        ).fetchall()
        return [
            Symbol(
                name=r["name"],
                kind=r["kind"],
                file=Path(r["file_path"]),
                line_start=r["line_start"] or 0,
                line_end=r["line_end"] or 0,
                language=r["language"] or "",
                signature=r["signature"] or "",
                docstring=r["docstring"] or "",
            )
            for r in rows
        ]

    def get_id(self, repo: str, file_path: str, name: str, kind: str) -> int | None:
        """Look up the rowid of a symbol by its identifying fields.

        Args:
            repo: Logical repository name.
            file_path: Path string as stored in the DB.
            name: Symbol name.
            kind: Symbol kind (e.g. "function", "class").

        Returns:
            Integer rowid or None if not found.
        """
        row = self._conn.execute(
            """
            SELECT id FROM symbols
            WHERE repo = ? AND file_path = ? AND name = ? AND kind = ?
            LIMIT 1
            """,
            (repo, file_path, name, kind),
        ).fetchone()
        return row["id"] if row else None

    def get_id_by_name(self, repo: str, name: str) -> int | None:
        """Look up the rowid of any symbol by name across all files.

        Used for cross-file edge resolution: finds the first class or function
        with the given name in the repository.  Prefers classes over other
        kinds since imports typically reference types.

        Args:
            repo: Logical repository name.
            name: Symbol name to search for.

        Returns:
            Integer rowid or None if not found.
        """
        row = self._conn.execute(
            """
            SELECT id FROM symbols
            WHERE repo = ? AND name = ?
            ORDER BY CASE kind WHEN 'class' THEN 0 WHEN 'function' THEN 1 ELSE 2 END
            LIMIT 1
            """,
            (repo, name),
        ).fetchone()
        return row["id"] if row else None

    def get_id_for_file(self, repo: str, file_path: str) -> int | None:
        """Return the rowid of the first symbol in *file_path*.

        Used to anchor file-path based edge endpoints when no specific symbol
        name is provided.

        Args:
            repo: Logical repository name.
            file_path: Absolute path string as stored in the DB.

        Returns:
            Integer rowid or None if the file has no indexed symbols.
        """
        row = self._conn.execute(
            """
            SELECT id FROM symbols
            WHERE repo = ? AND file_path = ?
            ORDER BY line_start
            LIMIT 1
            """,
            (repo, file_path),
        ).fetchone()
        return row["id"] if row else None

    def get_all(self, repo: str, limit: int = 10_000) -> list[Symbol]:
        """Return all symbols for a repository, up to *limit* rows.

        Args:
            repo: Logical repository name.
            limit: Maximum number of symbols to return (default 10 000).

        Returns:
            List of Symbol dataclass instances.
        """
        rows = self._conn.execute(
            """
            SELECT id, name, kind, file_path, line_start, line_end,
                   language, signature, docstring, community_id
            FROM symbols
            WHERE repo = ?
            LIMIT ?
            """,
            (repo, limit),
        ).fetchall()
        return [
            Symbol(
                name=r["name"],
                kind=r["kind"],
                file=Path(r["file_path"]),
                line_start=r["line_start"] or 0,
                line_end=r["line_end"] or 0,
                language=r["language"] or "",
                signature=r["signature"] or "",
                docstring=r["docstring"] or "",
                community_id=r["community_id"],
            )
            for r in rows
        ]

    def get_distinct_files(self, repo: str) -> list[str]:
        """Return the distinct file paths that have at least one symbol.

        Args:
            repo: Logical repository name.

        Returns:
            Sorted list of file path strings.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT file_path FROM symbols WHERE repo = ? ORDER BY file_path",
            (repo,),
        ).fetchall()
        return [r["file_path"] for r in rows]

    def count(self, repo: str) -> int:
        """Return the total number of symbols for a repository."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE repo = ?", (repo,)
        ).fetchone()
        return row[0]

    def update_community(self, repo: str, symbol_id: int, community_id: int) -> None:
        """Set the community_id for a given symbol."""
        self._conn.execute(
            "UPDATE symbols SET community_id=? WHERE repo=? AND id=?",
            (community_id, repo, symbol_id),
        )
        self._conn.commit()

    def get_communities(self, repo: str) -> dict[int, list[int]]:
        """Return a mapping of community_id -> list of symbol ids."""
        rows = self._conn.execute(
            "SELECT id, community_id FROM symbols WHERE repo=? AND community_id IS NOT NULL",
            (repo,),
        ).fetchall()
        result: dict[int, list[int]] = {}
        for row in rows:
            cid = row["community_id"]
            result.setdefault(cid, []).append(row["id"])
        return result


class EdgeRepository:
    """Typed access to the edges table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection."""
        self._conn = conn

    def add(
        self,
        edge: DependencyEdge,
        repo: str,
        from_id: int,
        to_id: int,
    ) -> int:
        """Insert an edge row and return its rowid.

        Args:
            edge: The DependencyEdge to persist.
            repo: Logical repository name.
            from_id: Rowid of the source symbol.
            to_id: Rowid of the target symbol.

        Returns:
            The integer rowid of the inserted row.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO edges (repo, from_symbol_id, to_symbol_id, edge_type, weight)
            VALUES (?, ?, ?, ?, ?)
            """,
            (repo, from_id, to_id, edge.edge_type, edge.weight),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def add_bulk(
        self,
        edges_with_ids: list[tuple[DependencyEdge, int, int]],
        repo: str,
    ) -> None:
        """Insert multiple edges in a single transaction.

        Args:
            edges_with_ids: List of (DependencyEdge, from_id, to_id) tuples.
            repo: Logical repository name.
        """
        self._conn.executemany(
            """
            INSERT INTO edges (repo, from_symbol_id, to_symbol_id, edge_type, weight)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (repo, from_id, to_id, edge.edge_type, edge.weight)
                for edge, from_id, to_id in edges_with_ids
            ],
        )
        self._conn.commit()

    def delete_by_file(self, repo: str, file_path: str) -> None:
        """Delete all edges originating from symbols in a given file.

        Args:
            repo: Logical repository name.
            file_path: Path string matching the symbols.file_path column.
        """
        self._conn.execute(
            """
            DELETE FROM edges
            WHERE repo = ?
              AND from_symbol_id IN (
                  SELECT id FROM symbols WHERE repo = ? AND file_path = ?
              )
            """,
            (repo, repo, file_path),
        )
        self._conn.commit()

    def get_adjacent_files(self, repo: str, file_path: str) -> list[str]:
        """Return file paths that share an edge with symbols in *file_path*.

        Useful for blast-radius calculation: given a changed file, this method
        returns all files that import from it or are imported by it.

        Args:
            repo: Logical repository name.
            file_path: Path string as stored in the DB.

        Returns:
            Sorted list of distinct adjacent file path strings, excluding
            *file_path* itself.
        """
        rows = self._conn.execute(
            """
            SELECT DISTINCT s.file_path
            FROM edges e
            JOIN symbols s
              ON s.id = e.from_symbol_id OR s.id = e.to_symbol_id
            WHERE e.repo = ?
              AND s.file_path != ?
              AND (
                e.from_symbol_id IN (
                    SELECT id FROM symbols WHERE repo = ? AND file_path = ?
                )
                OR e.to_symbol_id IN (
                    SELECT id FROM symbols WHERE repo = ? AND file_path = ?
                )
              )
            ORDER BY s.file_path
            """,
            (repo, file_path, repo, file_path, repo, file_path),
        ).fetchall()
        return [r["file_path"] for r in rows]

    def add_raw(self, repo: str, from_id: int, to_id: int, edge_type: str) -> None:
        """Insert an edge directly by integer symbol ids without name resolution."""
        self._conn.execute(
            "INSERT OR IGNORE INTO edges(repo, from_symbol_id, to_symbol_id, edge_type, weight) "
            "VALUES (?, ?, ?, ?, 1.0)",
            (repo, from_id, to_id, edge_type),
        )
        self._conn.commit()

    def get_all_edges(self, repo: str) -> list[tuple[int, int]]:
        """Return all (from_symbol_id, to_symbol_id) pairs for a repository."""
        rows = self._conn.execute(
            "SELECT from_symbol_id, to_symbol_id FROM edges WHERE repo=?", (repo,)
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def count(self, repo: str) -> int:
        """Return the total number of edges for a repository."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM edges WHERE repo = ?", (repo,)
        ).fetchone()
        return row[0]
