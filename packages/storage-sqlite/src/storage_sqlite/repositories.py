"""Repository classes for context-router's SQLite storage.

Each repository wraps a single domain entity and provides typed read/write
access. All SQL uses parameterized queries — never string interpolation.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol, SymbolRef
from contracts.models import Decision, Observation, PackFeedback, RuntimeSignal

# Matches identifier-shaped tokens for FTS5 query construction. Splits on
# anything that isn't a letter/digit/underscore so e.g. "unprepareResources
# error handling!" yields three clean tokens. Single-character tokens are
# kept (FTS5 will simply return zero matches for noise like "a"), but blank
# results are handled by the caller.
_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _split_fts_tokens(query: str) -> list[str]:
    """Tokenize *query* into FTS5-safe terms (letters, digits, underscores)."""
    return _FTS_TOKEN_RE.findall(query)


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

    def get_for_files(self, repo: str, file_paths: list[str] | set[str]) -> list[Symbol]:
        """Return all symbols belonging to *file_paths*, bypassing the get_all cap.

        ``get_all``'s 10,000-row cap silently drops files in large repos
        (django: 43k symbols → 33k invisible). When the orchestrator needs
        to guarantee that specific files (e.g. ``changed_files``) are
        represented in the candidate pool, it calls this helper to fetch
        them directly by path.
        """
        paths = list(file_paths)
        if not paths:
            return []
        placeholders = ",".join("?" * len(paths))
        rows = self._conn.execute(
            f"""
            SELECT id, name, kind, file_path, line_start, line_end,
                   language, signature, docstring, community_id
            FROM symbols
            WHERE repo = ? AND file_path IN ({placeholders})
            """,
            (repo, *paths),
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

    def search_fts(
        self, query: str, repo: str | None = None, limit: int = 200
    ) -> list[Symbol]:
        """Return symbols matching *query* via the BM25-ranked FTS5 index.

        Used by implement-mode (Phase 4 of v4.4.4) when there is no diff
        anchor, so ``get_all``'s untruncated 10K slice is unlikely to contain
        the symbols a query like ``"unprepareResources error handling"``
        actually needs.

        Args:
            query: Free-form natural-language tokens. Whitespace-only or
                empty input returns ``[]`` without hitting the database.
            repo: Optional repository scope. Defaults to ``None`` (all repos)
                so callers that index a single repo can omit it.
            limit: Maximum number of rows to return, ranked by FTS5 BM25.

        Returns:
            A list of :class:`Symbol` instances ordered by relevance
            (lowest BM25 first). Empty when the query is blank or the index
            has no matches.
        """
        if not query or not query.strip():
            return []

        # FTS5 MATCH expects a query string. Build a tolerant prefix-OR query
        # from the user's tokens so a phrase like "unprepareResources error
        # handling" matches symbol names and signatures even when the exact
        # phrase isn't present. Quotes are escaped per FTS5 rules ("" inside
        # a "..." string).
        tokens = [t for t in _split_fts_tokens(query) if t]
        if not tokens:
            return []
        match_expr = " OR ".join(f'"{t.replace(chr(34), chr(34) * 2)}"*' for t in tokens)

        sql = """
            SELECT s.id, s.name, s.kind, s.file_path, s.line_start, s.line_end,
                   s.language, s.signature, s.docstring, s.community_id
            FROM symbols_fts AS f
            JOIN symbols AS s ON s.id = f.rowid
            WHERE f.symbols_fts MATCH ?
        """
        params: list[object] = [match_expr]
        if repo is not None:
            sql += " AND s.repo = ?"
            params.append(repo)
        sql += " ORDER BY bm25(symbols_fts) LIMIT ?"
        params.append(int(limit))

        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # FTS5 not available, malformed query, or symbols_fts missing.
            # Caller is responsible for emitting a stderr warning; the
            # repository stays silent and just degrades to "no matches".
            return []
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
        from datetime import UTC
        from datetime import datetime as _dt
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

    def fetch_symbol_lines_batch(
        self,
        lookups: list[tuple[str, str, str]],  # (repo, file_path, symbol_name)
    ) -> dict[tuple[str, str, str], tuple[int, int]]:
        """Return line ranges for a batch of symbols in a single SQL query.

        Args:
            lookups: List of (repo, file_path, symbol_name) tuples to look up.

        Returns:
            Dict mapping (repo, file_path, symbol_name) → (line_start, line_end).
            Missing symbols are absent from the result (not KeyError).
        """
        if not lookups:
            return {}

        placeholders = ",".join(["(?,?,?)"] * len(lookups))
        flat_params = [v for t in lookups for v in t]
        rows = self._conn.execute(
            f"""
            WITH lookup(repo, file_path, name) AS (VALUES {placeholders})
            SELECT s.repo, s.file_path, s.name, s.line_start, s.line_end
            FROM symbols s
            JOIN lookup
              ON s.repo = lookup.repo
             AND s.file_path = lookup.file_path
             AND s.name = lookup.name
            """,
            flat_params,
        ).fetchall()
        return {
            (r["repo"], r["file_path"], r["name"]): (r["line_start"] or 0, r["line_end"] or 0)
            for r in rows
        }

    def get_untested_hotspots(
        self,
        repo: str,
        top_pct: float = 0.10,
        limit_cap: int = 50,
    ) -> list[tuple[SymbolRef, int]]:
        """Return high-inbound-degree symbols that have zero ``tested_by`` edges.

        Identifies the top ``top_pct`` of symbols (by inbound ``calls`` /
        ``imports`` edges — a cheap hub-score proxy) that are not the
        target of any ``tested_by`` edge.  This mirrors
        code-review-graph's ``get_knowledge_gaps`` tool and is the data
        source for the ``audit --untested-hotspots`` CLI subcommand.

        The effective ``LIMIT`` is ``min(round(total_hot * top_pct), limit_cap)``.
        If ``top_pct`` resolves to zero rows the cap is still honoured as
        a minimum of 1 so a single-file repo with one hot symbol is not
        filtered out.

        Args:
            repo: Logical repository name.
            top_pct: Fraction of hot symbols to include (default 0.10).
            limit_cap: Absolute upper bound on returned rows (default 50).

        Returns:
            List of ``(SymbolRef, inbound_degree)`` tuples, ordered by
            inbound degree descending.  Empty list when the repo has no
            qualifying symbols.
        """
        # Count distinct hot symbols so we can turn top_pct into a LIMIT.
        total_row = self._conn.execute(
            """
            SELECT COUNT(DISTINCT to_symbol_id) AS n
            FROM edges
            WHERE repo = ? AND edge_type IN ('calls', 'imports')
            """,
            (repo,),
        ).fetchone()
        total_hot = int(total_row["n"] or 0)
        if total_hot == 0:
            return []

        # round() + max(1, ...) ensures a single-hot-symbol repo still
        # surfaces its one row, which matches the registered smoke
        # expectation that this repo produces at least one result.
        effective_limit = max(1, min(round(total_hot * top_pct), limit_cap))

        rows = self._conn.execute(
            """
            WITH hot AS (
                SELECT to_symbol_id AS sid, COUNT(*) AS inbound
                FROM edges
                WHERE repo = ? AND edge_type IN ('calls', 'imports')
                GROUP BY to_symbol_id
            ),
            tested AS (
                -- ``tested_by`` edges point SUT (from) → test fn (to).
                -- The *SUT* is what has coverage, so we exclude
                -- ``from_symbol_id`` from the hotspot list.  See
                -- language-python/language-java/language-typescript for
                -- the producer side of the edge.
                SELECT DISTINCT from_symbol_id AS sid
                FROM edges
                WHERE repo = ? AND edge_type = 'tested_by'
            )
            SELECT s.id       AS id,
                   s.name     AS name,
                   s.kind     AS kind,
                   s.file_path AS file_path,
                   s.language AS language,
                   s.line_start AS line_start,
                   s.line_end AS line_end,
                   h.inbound  AS inbound
            FROM symbols s
            JOIN hot h ON h.sid = s.id
            WHERE s.repo = ?
              AND s.id NOT IN (SELECT sid FROM tested)
            ORDER BY h.inbound DESC, s.name ASC
            LIMIT ?
            """,
            (repo, repo, repo, effective_limit),
        ).fetchall()

        return [
            (
                SymbolRef(
                    id=r["id"],
                    name=r["name"],
                    kind=r["kind"],
                    file=Path(r["file_path"]),
                    language=r["language"] or "",
                    line_start=r["line_start"] or 0,
                    line_end=r["line_end"] or 0,
                ),
                int(r["inbound"]),
            )
            for r in rows
        ]


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

    def get_call_chain_symbols(
        self,
        repo: str,
        from_symbol_id: int,
        max_depth: int = 3,
    ) -> list[SymbolRef]:
        """Symbol-level BFS over ``calls`` edges from *from_symbol_id*.

        Returns one :class:`SymbolRef` per reachable callee with ``depth`` set
        to the minimum hop distance from the seed.  The seed itself is not
        included in the result.

        Args:
            repo: Logical repository name.
            from_symbol_id: Seed symbol id.
            max_depth: Maximum number of call-chain hops (1 = direct callees).

        Returns:
            List of SymbolRef, each at its minimum hop depth.  Order is
            BFS-insertion (approximately shortest-path-first).
        """
        seed_row = self._conn.execute(
            "SELECT id FROM symbols WHERE id=? AND repo=?",
            (from_symbol_id, repo),
        ).fetchone()
        if not seed_row:
            return []

        visited: set[int] = {from_symbol_id}
        queue: list[tuple[int, int]] = [(from_symbol_id, 0)]
        result: list[SymbolRef] = []

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
                if callee_id in visited:
                    continue
                visited.add(callee_id)
                meta = self._conn.execute(
                    "SELECT name, kind, file_path, language, line_start, line_end "
                    "FROM symbols WHERE id=?",
                    (callee_id,),
                ).fetchone()
                if meta:
                    result.append(
                        SymbolRef(
                            id=callee_id,
                            name=meta[0],
                            kind=meta[1],
                            file=Path(meta[2]),
                            language=meta[3] or "",
                            line_start=meta[4] or 0,
                            line_end=meta[5] or 0,
                            depth=depth + 1,
                        )
                    )
                queue.append((callee_id, depth + 1))

        return result

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

    def count_by_type(self, repo: str, edge_type: str) -> int:
        """Return the number of edges of a given type for a repository.

        Used by ``audit --untested-hotspots`` to detect the pre-v3 legacy
        case where zero ``tested_by`` edges are indexed — in that case the
        CLI surfaces a stderr warning rather than emitting an empty list
        (per the CLAUDE.md silent-failure rule).

        Args:
            repo: Logical repository name.
            edge_type: Edge type string (e.g. ``tested_by``, ``calls``).

        Returns:
            Integer row count.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) FROM edges WHERE repo = ? AND edge_type = ?",
            (repo, edge_type),
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
                (id, pack_id, repo_scope, useful, missing, noisy, too_much_ctx, reason,
                 files_read, query_text, query_embedding, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                fb.query_text,
                fb.query_embedding if fb.query_embedding else None,
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

    @staticmethod
    def _cosine_weight(current: bytes, row: bytes | None) -> float:
        """Return the cosine-similarity weight in [0, 1] (clamped).

        Returns 1.0 (full delta, legacy behaviour) when either side is
        empty/NULL — preserves v4.4.1 unweighted semantics for rows
        without an embedding or when the caller didn't supply one.
        """
        if not current or not row:
            return 1.0
        try:
            import numpy as np  # type: ignore[import]
            a = np.frombuffer(current, dtype=np.float32)
            b = np.frombuffer(row, dtype=np.float32)
            if a.shape != b.shape or a.size == 0:
                return 1.0
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            if denom == 0.0:
                return 1.0
            cos = float(np.dot(a, b) / denom)
            # Clamp negative similarity to 0 (orthogonal/opposing
            # queries don't get to *flip* the sign of an adjustment —
            # they should just contribute nothing).
            return max(0.0, min(1.0, cos))
        except Exception:  # numpy missing, malformed bytes, etc.
            return 1.0

    def get_file_adjustments(
        self,
        min_count: int = 3,
        repo_scope: str = "",
        current_query_embedding: bytes = b"",
    ) -> dict[str, float]:
        """Return per-file confidence adjustments derived from feedback.

        Three signals contribute (each gated at >= ``min_count`` raw
        occurrences):
          * ``missing``  → +0.05  (file should have been in the pack)
          * ``noisy``    → -0.10  (file was in the pack but irrelevant)
          * ``files_read`` → +0.03  (v4.4 Phase 4: file was in the pack AND
            actually consumed by the agent — a positive signal that the
            ranker chose well)

        v4.4.2 Phase 6: when ``current_query_embedding`` is supplied,
        each contributing row is cosine-weighted against the current
        query's embedding. The threshold still gates on the *raw* row
        count; the weighted-sum / count ratio scales the per-row delta.
        Legacy rows (NULL embedding) and rows without a current
        embedding contribute their full delta — backward-compatible.

        Signals compose: a file with 5 reads + 3 noisy reports nets
        ``+0.03 - 0.10 = -0.07``. The smaller magnitude on ``files_read``
        (vs. explicit ``noisy`` / ``missing``) reflects that "agent
        consumed it" is a weaker positive than "agent explicitly
        complained / praised it".

        Args:
            min_count: Minimum occurrences before an adjustment is applied.
            repo_scope: Optional repository scope. Includes legacy blank-scope rows.
            current_query_embedding: Optional float32 bytes of the current
                query embedding. Empty → unweighted (v4.4.1 behaviour).

        Returns:
            Dict mapping file path → confidence delta.
        """
        predicate, scope_params = self._scope_predicate(repo_scope)
        rows = self._conn.execute(
            f"""
            SELECT missing, noisy, files_read, query_embedding
            FROM pack_feedback
            WHERE {predicate}
            """,
            scope_params,
        ).fetchall()

        missing_w: dict[str, float] = {}
        missing_n: dict[str, int] = {}
        noisy_w: dict[str, float] = {}
        noisy_n: dict[str, int] = {}
        read_w: dict[str, float] = {}
        read_n: dict[str, int] = {}
        for r in rows:
            row_emb_raw = (
                r["query_embedding"] if "query_embedding" in r.keys() else None
            )
            w = self._cosine_weight(current_query_embedding, row_emb_raw)
            for path in json.loads(r["missing"] or "[]"):
                missing_w[path] = missing_w.get(path, 0.0) + w
                missing_n[path] = missing_n.get(path, 0) + 1
            for path in json.loads(r["noisy"] or "[]"):
                noisy_w[path] = noisy_w.get(path, 0.0) + w
                noisy_n[path] = noisy_n.get(path, 0) + 1
            # files_read may be absent on rows older than migration 0007.
            files_read_raw = (
                r["files_read"] if "files_read" in r.keys() else "[]"
            )
            for path in json.loads(files_read_raw or "[]"):
                read_w[path] = read_w.get(path, 0.0) + w
                read_n[path] = read_n.get(path, 0) + 1

        adjustments: dict[str, float] = {}
        for path, n in missing_n.items():
            if n >= min_count:
                adjustments[path] = adjustments.get(path, 0.0) + 0.05 * (
                    missing_w[path] / n
                )
        for path, n in noisy_n.items():
            if n >= min_count:
                adjustments[path] = adjustments.get(path, 0.0) - 0.10 * (
                    noisy_w[path] / n
                )
        for path, n in read_n.items():
            if n >= min_count:
                adjustments[path] = adjustments.get(path, 0.0) + 0.03 * (
                    read_w[path] / n
                )
        return adjustments

    def _row_to_feedback(self, row: sqlite3.Row) -> PackFeedback:
        """Convert a sqlite3.Row to a PackFeedback model."""
        useful_raw = row["useful"]
        useful = None if useful_raw is None else bool(useful_raw)
        # files_read may be absent on rows created before migration 0007
        files_read_raw = row["files_read"] if "files_read" in row.keys() else "[]"
        # query_text / query_embedding may be absent on rows created before
        # migration 0014 (v4.4.2 Phase 6). Defensive read mirrors files_read.
        query_text = (
            row["query_text"]
            if "query_text" in row.keys() and row["query_text"] is not None
            else ""
        )
        query_embedding_raw = (
            row["query_embedding"] if "query_embedding" in row.keys() else None
        )
        query_embedding = (
            bytes(query_embedding_raw) if query_embedding_raw else b""
        )
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
            query_text=query_text,
            query_embedding=query_embedding,
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )


class ContractRepository:
    """Typed access to the service-contract tables (migration 0011).

    Signatures only — we store the shape needed to infer cross-repo links
    (method+path, service+rpc, operation name+kind) and nothing else.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection.

        Args:
            conn: An open sqlite3.Connection (caller owns lifetime).
        """
        self._conn = conn

    # ------------------------------------------------------------------
    # API endpoints (OpenAPI)
    # ------------------------------------------------------------------

    def upsert_api_endpoint(
        self,
        repo: str,
        method: str,
        path: str,
        operation_id: str = "",
        source_file: str = "",
        line: int = 0,
    ) -> None:
        """Insert or replace a single API endpoint row.

        Uniqueness is on ``(repo, method, path)``.
        """
        self._conn.execute(
            """
            INSERT INTO api_endpoints
                (repo, method, path, operation_id, source_file, line)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo, method, path) DO UPDATE SET
                operation_id = excluded.operation_id,
                source_file  = excluded.source_file,
                line         = excluded.line
            """,
            (repo, method.upper(), path, operation_id, source_file, line),
        )
        self._conn.commit()

    def list_api_endpoints(self, repo: str) -> list[dict]:
        """List every API endpoint row for *repo*, sorted by method+path."""
        rows = self._conn.execute(
            """
            SELECT method, path, operation_id, source_file, line
            FROM api_endpoints
            WHERE repo = ?
            ORDER BY method, path
            """,
            (repo,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # gRPC services
    # ------------------------------------------------------------------

    def upsert_grpc(
        self,
        repo: str,
        service: str,
        rpc: str,
        request_type: str = "",
        response_type: str = "",
        source_file: str = "",
        line: int = 0,
    ) -> None:
        """Insert or replace a single gRPC service/rpc row."""
        self._conn.execute(
            """
            INSERT INTO grpc_services
                (repo, service, rpc, request_type, response_type, source_file, line)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo, service, rpc) DO UPDATE SET
                request_type  = excluded.request_type,
                response_type = excluded.response_type,
                source_file   = excluded.source_file,
                line          = excluded.line
            """,
            (repo, service, rpc, request_type, response_type, source_file, line),
        )
        self._conn.commit()

    def list_grpc(self, repo: str) -> list[dict]:
        """List every gRPC row for *repo*, sorted by service+rpc."""
        rows = self._conn.execute(
            """
            SELECT service, rpc, request_type, response_type, source_file, line
            FROM grpc_services
            WHERE repo = ?
            ORDER BY service, rpc
            """,
            (repo,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # GraphQL operations
    # ------------------------------------------------------------------

    def upsert_graphql(
        self,
        repo: str,
        name: str,
        kind: str,
        source_file: str = "",
        line: int = 0,
    ) -> None:
        """Insert or replace a single GraphQL operation row."""
        self._conn.execute(
            """
            INSERT INTO graphql_operations
                (repo, name, kind, source_file, line)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repo, name, kind) DO UPDATE SET
                source_file = excluded.source_file,
                line        = excluded.line
            """,
            (repo, name, kind, source_file, line),
        )
        self._conn.commit()

    def list_graphql(self, repo: str) -> list[dict]:
        """List every GraphQL operation row for *repo*."""
        rows = self._conn.execute(
            """
            SELECT name, kind, source_file, line
            FROM graphql_operations
            WHERE repo = ?
            ORDER BY kind, name
            """,
            (repo,),
        ).fetchall()
        return [dict(r) for r in rows]


class PackCacheRepository:
    """Typed access to the ``pack_cache`` table (migration 0012).

    Persistent L2 cache for ranked :class:`ContextPack` results. Survives
    CLI process exits so that the second ``context-router pack`` call with
    the same inputs skips candidate building and ranking. TTL is enforced
    on read (default 300s, matching the in-process L1 ``TTLCache``).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection.

        Args:
            conn: An open sqlite3.Connection (caller owns lifetime).
        """
        self._conn = conn

    def get(
        self,
        cache_key: str,
        repo_id: str,
        ttl_seconds: float,
        *,
        now: float | None = None,
    ) -> str | None:
        """Return the cached pack JSON for (cache_key, repo_id) or None.

        Args:
            cache_key: Stable Python-computed hash of build_pack inputs.
            repo_id: sha1(db_mtime || repo_name) — changes on re-index.
            ttl_seconds: Entries older than this are treated as misses.
            now: Optional unix-epoch override (for tests). Defaults to
                ``time.time()``.

        Returns:
            The serialized pack JSON string, or ``None`` on cache miss /
            expiry. Expired rows are not deleted eagerly; invalidate() or
            the next insert's ``ON CONFLICT`` clause will reclaim them.
        """
        import time

        current = time.time() if now is None else now
        row = self._conn.execute(
            """
            SELECT pack_json, inserted_at
            FROM pack_cache
            WHERE cache_key = ? AND repo_id = ?
            """,
            (cache_key, repo_id),
        ).fetchone()
        if row is None:
            return None
        if (current - float(row["inserted_at"])) > ttl_seconds:
            return None
        return str(row["pack_json"])

    def put(
        self,
        cache_key: str,
        repo_id: str,
        pack_json: str,
        *,
        now: float | None = None,
    ) -> None:
        """Insert-or-replace a cache entry for (cache_key, repo_id).

        Args:
            cache_key: Stable hash of build_pack inputs.
            repo_id: sha1(db_mtime || repo_name).
            pack_json: ``ContextPack.model_dump_json()`` output.
            now: Optional unix-epoch override (for tests). Defaults to
                ``time.time()``.
        """
        import time

        inserted_at = time.time() if now is None else now
        self._conn.execute(
            """
            INSERT INTO pack_cache (cache_key, repo_id, pack_json, inserted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(cache_key, repo_id) DO UPDATE SET
                pack_json   = excluded.pack_json,
                inserted_at = excluded.inserted_at
            """,
            (cache_key, repo_id, pack_json, inserted_at),
        )
        self._conn.commit()

    def invalidate_repo(self, repo_id: str) -> int:
        """Delete every entry for *repo_id*. Returns row count deleted."""
        cur = self._conn.execute(
            "DELETE FROM pack_cache WHERE repo_id = ?",
            (repo_id,),
        )
        self._conn.commit()
        return cur.rowcount or 0

    def invalidate_all(self) -> int:
        """Delete every entry. Returns row count deleted."""
        cur = self._conn.execute("DELETE FROM pack_cache")
        self._conn.commit()
        return cur.rowcount or 0


class EmbeddingRepository:
    """Typed access to the ``embeddings`` table (migration 0013).

    Persistent vector store for symbol embeddings — populated by
    ``context-router embed`` and read by the ranker's semantic-boost
    path so a ``pack --with-semantic`` call avoids re-encoding every
    candidate. Vectors are stored as packed float32 BLOBs (the
    ``np.array(...).astype(np.float32).tobytes()`` round trip),
    which is ~4× cheaper than JSON for 384-dim MiniLM vectors.

    All vectors must be the same length per ``(repo, model)`` pair;
    callers are responsible for matching the model name across writes
    and reads. The repo enforces nothing beyond table-level constraints.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize with an open database connection.

        Args:
            conn: An open sqlite3.Connection (caller owns lifetime).
        """
        self._conn = conn

    def upsert_batch(
        self,
        repo: str,
        model: str,
        rows: list[tuple[int, bytes]],
        *,
        now: float | None = None,
    ) -> int:
        """Insert-or-replace embeddings for many symbols in one transaction.

        Args:
            repo: Logical repository name (matches ``symbols.repo``).
            model: Model identifier (e.g. ``"all-MiniLM-L6-v2"``).
            rows: Iterable of ``(symbol_id, vector_bytes)`` tuples. Each
                ``vector_bytes`` value must be a packed float32 array
                (use ``np.asarray(v, dtype=np.float32).tobytes()``).
            now: Optional unix-epoch override (defaults to ``time.time()``).

        Returns:
            Number of rows accepted (equal to ``len(rows)``).
        """
        import time

        built_at = time.time() if now is None else now
        params = [
            (repo, sid, model, vec, built_at)
            for sid, vec in rows
        ]
        self._conn.executemany(
            """
            INSERT INTO embeddings (repo, symbol_id, model, vector, built_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repo, symbol_id, model) DO UPDATE SET
                vector   = excluded.vector,
                built_at = excluded.built_at
            """,
            params,
        )
        self._conn.commit()
        return len(params)

    def get_vector(
        self, repo: str, symbol_id: int, model: str
    ) -> bytes | None:
        """Return the stored vector blob for a single symbol or None."""
        row = self._conn.execute(
            """
            SELECT vector FROM embeddings
            WHERE repo = ? AND symbol_id = ? AND model = ?
            """,
            (repo, symbol_id, model),
        ).fetchone()
        if row is None:
            return None
        return bytes(row["vector"])

    def bulk_get_vectors(
        self, repo: str, symbol_ids: list[int], model: str
    ) -> dict[int, bytes]:
        """Return a {symbol_id: vector_bytes} mapping for the given ids.

        Symbols without a stored vector are simply absent from the result.
        Empty input returns an empty dict (no SQL is executed).

        Args:
            repo: Logical repository name.
            symbol_ids: Symbol ids to look up.
            model: Model identifier — only rows matching this model name
                are returned.
        """
        if not symbol_ids:
            return {}
        # Chunk to keep the parameter list under SQLite's default 999 limit.
        # We use 500 to leave headroom for the two leading params.
        chunk = 500
        result: dict[int, bytes] = {}
        for start in range(0, len(symbol_ids), chunk):
            ids = symbol_ids[start : start + chunk]
            placeholders = ",".join("?" * len(ids))
            rows = self._conn.execute(
                f"""
                SELECT symbol_id, vector FROM embeddings
                WHERE repo = ? AND model = ?
                  AND symbol_id IN ({placeholders})
                """,
                (repo, model, *ids),
            ).fetchall()
            for r in rows:
                result[int(r["symbol_id"])] = bytes(r["vector"])
        return result

    def delete_all_for_repo(self, repo: str, model: str | None = None) -> int:
        """Delete every embedding row for *repo*. Returns row count deleted.

        Args:
            repo: Logical repository name.
            model: If provided, only delete rows for this model name.
                Otherwise wipe every model for the repo.
        """
        if model is None:
            cur = self._conn.execute(
                "DELETE FROM embeddings WHERE repo = ?",
                (repo,),
            )
        else:
            cur = self._conn.execute(
                "DELETE FROM embeddings WHERE repo = ? AND model = ?",
                (repo, model),
            )
        self._conn.commit()
        return cur.rowcount or 0

    def count(self, repo: str, model: str | None = None) -> int:
        """Return the number of stored embeddings for *repo* (and optionally model)."""
        if model is None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM embeddings WHERE repo = ?", (repo,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM embeddings WHERE repo = ? AND model = ?",
                (repo, model),
            ).fetchone()
        return int(row[0]) if row else 0
