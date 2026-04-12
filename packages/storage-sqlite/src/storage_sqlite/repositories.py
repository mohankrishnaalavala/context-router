"""Repository classes for context-router's SQLite storage.

Each repository wraps a single domain entity and provides typed read/write
access. All SQL uses parameterized queries — never string interpolation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

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
                 failures_seen, fix_summary, commit_sha, repo_scope)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            JOIN observations_fts fts ON o.id = fts.rowid
            WHERE observations_fts MATCH ?
            ORDER BY o.id DESC
            """,
            (query,),
        ).fetchall()
        return [self._row_to_observation(r) for r in rows]

    def _row_to_observation(self, row: sqlite3.Row) -> Observation:
        """Convert a sqlite3.Row to an Observation model."""
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
