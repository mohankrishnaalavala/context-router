"""Repository classes for context-router's SQLite storage.

Each repository wraps a single domain entity and provides typed read/write
access. All SQL uses parameterized queries — never string interpolation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol
from contracts.models import Decision, Observation, PackFeedback, RuntimeSignal


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
                 failures_seen, fix_summary, commit_sha, repo_scope, task_hash,
                 confidence_score, access_count, last_accessed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                obs.confidence_score,
                obs.access_count,
                obs.last_accessed_at.isoformat() if obs.last_accessed_at else None,
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
            List of matching Observation objects, best BM25 relevance first.
        """
        rows = self._conn.execute(
            """
            SELECT o.*
            FROM observations o
            JOIN observations_fts fts ON o.rowid = fts.rowid
            WHERE observations_fts MATCH ?
            ORDER BY fts.rank
            """,
            (query,),
        ).fetchall()
        return [self._row_to_observation(r) for r in rows]

    def record_access(self, rowid: int) -> None:
        """Increment access_count and update last_accessed_at for an observation.

        Called by the orchestrator each time an observation is included in a pack.

        Args:
            rowid: The SQLite rowid of the observation.
        """
        self._conn.execute(
            "UPDATE observations SET access_count = access_count + 1, "
            "last_accessed_at = ? WHERE rowid = ?",
            (datetime.now(UTC).isoformat(), rowid),
        )
        self._conn.commit()

    def get_all(self) -> list[Observation]:
        """Return all observations ordered by creation time descending."""
        rows = self._conn.execute(
            "SELECT * FROM observations ORDER BY id DESC"
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
        last_acc = row["last_accessed_at"] if "last_accessed_at" in keys else None
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
            confidence_score=float(row["confidence_score"]) if "confidence_score" in keys else 0.5,
            access_count=int(row["access_count"]) if "access_count" in keys else 0,
            last_accessed_at=datetime.fromisoformat(last_acc) if last_acc else None,
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

    def mark_superseded(self, old_id: str, new_id: str) -> None:
        """Set old decision status=superseded and link it to new_id.

        Args:
            old_id: UUID of the decision being replaced.
            new_id: UUID of the new decision that supersedes it.
        """
        self._conn.execute(
            "UPDATE decisions SET status = 'superseded', superseded_by = ? WHERE id = ?",
            (new_id, old_id),
        )
        self._conn.commit()

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
            ORDER BY fts.rank
            """,
            (query,),
        ).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def _row_to_decision(self, row: sqlite3.Row) -> Decision:
        """Convert a sqlite3.Row to a Decision model."""
        keys = row.keys() if hasattr(row, "keys") else []
        last_rev = row["last_reviewed_at"] if "last_reviewed_at" in keys else None
        return Decision(
            id=row["id"],
            title=row["title"],
            status=row["status"],
            context=row["context"] or "",
            decision=row["decision"] or "",
            consequences=row["consequences"] or "",
            tags=json.loads(row["tags"] or "[]"),
            created_at=datetime.fromisoformat(row["created_at"]),
            confidence=float(row["confidence"]) if "confidence" in keys else 0.8,
            last_reviewed_at=datetime.fromisoformat(last_rev) if last_rev else None,
            superseded_by=row["superseded_by"] or "" if "superseded_by" in keys else "",
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
                (source, severity, message, stack, paths, timestamp,
                 error_hash, top_frames, failing_tests)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sig.source,
                sig.severity,
                sig.message,
                json.dumps(sig.stack),
                json.dumps([str(p) for p in sig.paths]),
                sig.timestamp.isoformat(),
                sig.error_hash,
                json.dumps(sig.top_frames),
                json.dumps(sig.failing_tests),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    def find_by_error_hash(self, error_hash: str) -> list[RuntimeSignal]:
        """Return signals matching the given error_hash (most recent first).

        Args:
            error_hash: 16-char normalized error signature hash.

        Returns:
            Matching RuntimeSignal objects, newest first.
        """
        if not error_hash:
            return []
        rows = self._conn.execute(
            "SELECT * FROM runtime_signals WHERE error_hash = ? ORDER BY timestamp DESC",
            (error_hash,),
        ).fetchall()
        return [self._row_to_signal(r) for r in rows]

    def get_recent(self, limit: int = 50) -> list[RuntimeSignal]:
        """Return the most recently added runtime signals.

        Args:
            limit: Maximum number of signals to return.

        Returns:
            RuntimeSignal objects, newest first.
        """
        rows = self._conn.execute(
            "SELECT * FROM runtime_signals ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_signal(r) for r in rows]

    def _row_to_signal(self, row: sqlite3.Row) -> RuntimeSignal:
        """Convert a sqlite3.Row to a RuntimeSignal model."""
        keys = row.keys() if hasattr(row, "keys") else []
        return RuntimeSignal(
            source=row["source"] or "",
            severity=row["severity"],
            message=row["message"],
            stack=json.loads(row["stack"] or "[]"),
            paths=[Path(p) for p in json.loads(row["paths"] or "[]")],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            error_hash=row["error_hash"] if "error_hash" in keys else "",
            top_frames=json.loads(row["top_frames"]) if "top_frames" in keys else [],
            failing_tests=json.loads(row["failing_tests"]) if "failing_tests" in keys else [],
        )


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
            SELECT id, name, kind, file_path, line_start, line_end,
                   language, signature, docstring, community_id
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
                community_id=r["community_id"],
                id=r["id"],
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
                id=r["id"],
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

    def record_access(self, file_path: str, name: str) -> None:
        """Increment access_count and update last_accessed_at for a symbol.

        Called after a pack is built to track selection frequency.

        Args:
            file_path: The file path of the symbol as stored in the DB.
            name: The symbol name.
        """
        from datetime import UTC, datetime as _dt
        self._conn.execute(
            "UPDATE symbols SET access_count = access_count + 1, "
            "last_accessed_at = ? WHERE file_path = ? AND name = ?",
            (_dt.now(UTC).isoformat(), file_path, name),
        )
        self._conn.commit()

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

        Uses a UNION of two indexed paths (``idx_edges_repo_from`` +
        ``idx_edges_repo_to``) so each side of the edge hits an index
        directly; the prior OR-joined query could fall back to a scan on
        large repos.
        """
        rows = self._conn.execute(
            """
            SELECT s2.file_path FROM edges e
            JOIN symbols s1 ON s1.id = e.from_symbol_id
            JOIN symbols s2 ON s2.id = e.to_symbol_id
            WHERE e.repo = ? AND s1.file_path = ? AND s2.file_path != ?

            UNION

            SELECT s1.file_path FROM edges e
            JOIN symbols s1 ON s1.id = e.from_symbol_id
            JOIN symbols s2 ON s2.id = e.to_symbol_id
            WHERE e.repo = ? AND s2.file_path = ? AND s1.file_path != ?

            ORDER BY 1
            """,
            (repo, file_path, file_path, repo, file_path, file_path),
        ).fetchall()
        return [r["file_path"] for r in rows]

    def get_call_chain_files(
        self,
        repo: str,
        from_file_path: str,
        max_depth: int = 3,
    ) -> list[tuple[str, int]]:
        """BFS traversal of ``calls`` edges up to *max_depth* hops from all
        symbols in *from_file_path*.

        Returns ``[(callee_file_path, hop_depth), ...]`` for each reachable
        callee file, excluding *from_file_path* itself.  Each file appears
        only once at its minimum hop depth.

        Args:
            repo: Logical repository name.
            from_file_path: Starting file path as stored in the DB.
            max_depth: Maximum number of call-chain hops to traverse (1–N).

        Returns:
            List of (file_path, depth) tuples, unordered.
        """
        seed_rows = self._conn.execute(
            "SELECT id FROM symbols WHERE repo=? AND file_path=?",
            (repo, from_file_path),
        ).fetchall()
        seed_ids = {r[0] for r in seed_rows}
        if not seed_ids:
            return []

        visited_ids: set[int] = set(seed_ids)
        queue: list[tuple[int, int]] = [(sid, 0) for sid in seed_ids]
        result_files: dict[str, int] = {}  # file_path -> min hop depth

        while queue:
            curr_id, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            rows = self._conn.execute(
                "SELECT to_symbol_id FROM edges "
                "WHERE repo=? AND from_symbol_id=? AND edge_type='calls'",
                (repo, curr_id),
            ).fetchall()
            for row in rows:
                callee_id = row[0]
                if callee_id in visited_ids:
                    continue
                visited_ids.add(callee_id)
                fp_row = self._conn.execute(
                    "SELECT file_path FROM symbols WHERE id=?", (callee_id,)
                ).fetchone()
                if fp_row:
                    fp = fp_row[0]
                    if fp != from_file_path and fp not in result_files:
                        result_files[fp] = depth + 1
                queue.append((callee_id, depth + 1))

        return list(result_files.items())

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


class PackFeedbackRepository:
    """Typed access to the pack_feedback table (Phase 6 — agent feedback loop)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection."""
        self._conn = conn

    @staticmethod
    def _scope_predicate(repo_scope: str) -> tuple[str, tuple[str, ...]]:
        """Return a SQL predicate and bound params for feedback scope filtering."""
        if repo_scope:
            return "(repo_scope = ? OR repo_scope = '')", (repo_scope,)
        return "1 = 1", ()

    def add(self, fb: PackFeedback) -> str:
        """Insert a feedback record and return its id.

        Args:
            fb: PackFeedback to persist.

        Returns:
            UUID string of the inserted record.
        """
        self._conn.execute(
            """
            INSERT INTO pack_feedback
                (id, pack_id, repo_scope, useful, missing, noisy, too_much_ctx, reason, files_read, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fb.id,
                fb.pack_id,
                fb.repo_scope or "",
                None if fb.useful is None else (1 if fb.useful else 0),
                json.dumps(fb.missing),
                json.dumps(fb.noisy),
                1 if fb.too_much_context else 0,
                fb.reason,
                json.dumps(fb.files_read),
                fb.timestamp.isoformat(),
            ),
        )
        self._conn.commit()
        return fb.id

    def get_for_pack(self, pack_id: str, repo_scope: str = "") -> list[PackFeedback]:
        """Return all feedback records for a specific pack.

        Args:
            pack_id: UUID of the ContextPack.
            repo_scope: Optional repository scope. Includes legacy blank-scope rows.

        Returns:
            List of PackFeedback objects.
        """
        predicate, scope_params = self._scope_predicate(repo_scope)
        rows = self._conn.execute(
            f"""
            SELECT * FROM pack_feedback
            WHERE pack_id = ? AND {predicate}
            ORDER BY timestamp DESC
            """,
            (pack_id, *scope_params),
        ).fetchall()
        return [self._row_to_feedback(r) for r in rows]

    def get_all(self, limit: int = 100, repo_scope: str = "") -> list[PackFeedback]:
        """Return the most recent feedback records.

        Args:
            limit: Maximum number of records to return.
            repo_scope: Optional repository scope. Includes legacy blank-scope rows.

        Returns:
            List of PackFeedback objects, newest first.
        """
        predicate, scope_params = self._scope_predicate(repo_scope)
        rows = self._conn.execute(
            f"""
            SELECT * FROM pack_feedback
            WHERE {predicate}
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (*scope_params, limit),
        ).fetchall()
        return [self._row_to_feedback(r) for r in rows]

    def aggregate_stats(self, repo_scope: str = "") -> dict:
        """Compute aggregate feedback statistics.

        Args:
            repo_scope: Optional repository scope. Includes legacy blank-scope rows.

        Returns:
            Dict with keys: total, useful_count, not_useful_count, useful_pct,
            top_missing (top 5 paths), top_noisy (top 5 paths),
            read_overlap_pct (when ≥5 reports include files_read),
            noise_ratio_pct (when ≥5 reports include files_read).
        """
        predicate, scope_params = self._scope_predicate(repo_scope)
        rows = self._conn.execute(
            f"""
            SELECT useful, missing, noisy, files_read
            FROM pack_feedback
            WHERE {predicate}
            """,
            scope_params,
        ).fetchall()

        total = len(rows)
        useful_count = sum(1 for r in rows if r["useful"] == 1)
        not_useful_count = sum(1 for r in rows if r["useful"] == 0)

        # Count file-level missing/noisy frequencies
        missing_freq: dict[str, int] = {}
        noisy_freq: dict[str, int] = {}
        for r in rows:
            for path in json.loads(r["missing"] or "[]"):
                missing_freq[path] = missing_freq.get(path, 0) + 1
            for path in json.loads(r["noisy"] or "[]"):
                noisy_freq[path] = noisy_freq.get(path, 0) + 1

        top_missing = sorted(missing_freq, key=lambda k: missing_freq[k], reverse=True)[:5]
        top_noisy = sorted(noisy_freq, key=lambda k: noisy_freq[k], reverse=True)[:5]

        result: dict = {
            "total": total,
            "useful_count": useful_count,
            "not_useful_count": not_useful_count,
            "useful_pct": round(useful_count / total * 100, 1) if total else 0.0,
            "top_missing": top_missing,
            "top_noisy": top_noisy,
        }

        # Read coverage — only computed when ≥5 reports include files_read
        rows_with_reads = [
            r for r in rows
            if json.loads(r["files_read"] or "[]")
        ]
        if len(rows_with_reads) >= 5:
            overlap_rates: list[float] = []
            noise_rates: list[float] = []
            for r in rows_with_reads:
                fr = set(json.loads(r["files_read"]))
                # For now we can only compute noise from noisy list vs files_read
                noisy_set = set(json.loads(r["noisy"] or "[]"))
                # overlap: what fraction of files_read was NOT in noisy (i.e. useful)
                if fr:
                    useful_reads = fr - noisy_set
                    overlap_rates.append(len(useful_reads) / len(fr))
                    noise_rates.append(len(fr & noisy_set) / len(fr))
            if overlap_rates:
                result["read_overlap_pct"] = round(
                    sum(overlap_rates) / len(overlap_rates) * 100, 1
                )
                result["noise_ratio_pct"] = round(
                    sum(noise_rates) / len(noise_rates) * 100, 1
                )
                result["reports_with_files_read"] = len(rows_with_reads)

        return result

    def get_file_adjustments(
        self,
        min_count: int = 3,
        repo_scope: str = "",
    ) -> dict[str, float]:
        """Return per-file confidence adjustments derived from feedback.

        Files frequently in 'missing' get +0.05; frequently in 'noisy' get -0.10.
        Only applied when a file appears in feedback >= min_count times.

        Args:
            min_count: Minimum occurrences before an adjustment is applied.
            repo_scope: Optional repository scope. Includes legacy blank-scope rows.

        Returns:
            Dict mapping file path → confidence delta.
        """
        predicate, scope_params = self._scope_predicate(repo_scope)
        rows = self._conn.execute(
            f"""
            SELECT missing, noisy
            FROM pack_feedback
            WHERE {predicate}
            """,
            scope_params,
        ).fetchall()

        missing_freq: dict[str, int] = {}
        noisy_freq: dict[str, int] = {}
        for r in rows:
            for path in json.loads(r["missing"] or "[]"):
                missing_freq[path] = missing_freq.get(path, 0) + 1
            for path in json.loads(r["noisy"] or "[]"):
                noisy_freq[path] = noisy_freq.get(path, 0) + 1

        adjustments: dict[str, float] = {}
        for path, count in missing_freq.items():
            if count >= min_count:
                adjustments[path] = adjustments.get(path, 0.0) + 0.05
        for path, count in noisy_freq.items():
            if count >= min_count:
                adjustments[path] = adjustments.get(path, 0.0) - 0.10
        return adjustments

    def _row_to_feedback(self, row: sqlite3.Row) -> PackFeedback:
        """Convert a sqlite3.Row to a PackFeedback model."""
        useful_raw = row["useful"]
        useful = None if useful_raw is None else bool(useful_raw)
        # files_read may be absent on rows created before migration 0007
        files_read_raw = row["files_read"] if "files_read" in row.keys() else "[]"
        return PackFeedback(
            id=row["id"],
            pack_id=row["pack_id"],
            repo_scope=row["repo_scope"] if "repo_scope" in row.keys() else "",
            useful=useful,
            missing=json.loads(row["missing"] or "[]"),
            noisy=json.loads(row["noisy"] or "[]"),
            too_much_context=bool(row["too_much_ctx"]),
            reason=row["reason"] or "",
            files_read=json.loads(files_read_raw or "[]"),
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
