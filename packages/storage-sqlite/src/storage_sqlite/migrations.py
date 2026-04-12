"""Migration runner for the context-router SQLite schema.

Reads numbered *.sql files from the migrations directory and applies
any that haven't been applied yet, tracking state in schema_version.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class MigrationRunner:
    """Applies SQL migration files in lexicographic order, skipping already-applied ones."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        """Initialize with an open SQLite connection.

        Args:
            connection: An open sqlite3.Connection (caller owns lifetime).
        """
        self._conn = connection

    def current_version(self) -> int:
        """Return the currently applied migration version (0 if none applied)."""
        try:
            row = self._conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            return row[0] if row and row[0] is not None else 0
        except sqlite3.OperationalError:
            return 0

    def apply_all(self, migrations_dir: Path) -> None:
        """Apply all unapplied migration files from migrations_dir.

        Files are sorted lexicographically, so they must be named with
        zero-padded numbers (e.g. 0001_initial.sql, 0002_add_index.sql).

        Args:
            migrations_dir: Directory containing *.sql migration files.
        """
        sql_files = sorted(migrations_dir.glob("*.sql"))
        current = self.current_version()

        for sql_file in sql_files:
            # Extract version number from filename prefix (e.g. "0001")
            prefix = sql_file.stem.split("_")[0]
            try:
                file_version = int(prefix)
            except ValueError:
                continue

            if file_version <= current:
                continue

            sql = sql_file.read_text(encoding="utf-8")
            self._conn.executescript(sql)
            self._conn.execute(
                "INSERT OR REPLACE INTO schema_version(version) VALUES (?)",
                (file_version,),
            )
            self._conn.commit()
