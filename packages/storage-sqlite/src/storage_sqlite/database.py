"""SQLite database lifecycle management for context-router.

Database is the only entry point for obtaining a connection. Consumers
must use repository classes (repositories.py) rather than querying
directly through the connection.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from storage_sqlite.migrations import MigrationRunner

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    """Manages connection lifecycle and schema initialization for context-router's SQLite DB."""

    def __init__(self, db_path: Path) -> None:
        """Create a Database manager for the given path.

        Args:
            db_path: Path to the .db file. Will be created if absent.
        """
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """Open the SQLite connection with recommended pragmas.

        Returns:
            An open sqlite3.Connection with row_factory = sqlite3.Row,
            WAL journal mode, and foreign key enforcement enabled.
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        self._conn = conn
        return conn

    def initialize(self) -> None:
        """Connect (if not already) and apply all pending migrations."""
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        MigrationRunner(self._conn).apply_all(_MIGRATIONS_DIR)

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the open connection.

        Raises:
            RuntimeError: If initialize() or connect() has not been called.
        """
        if self._conn is None:
            raise RuntimeError(
                "Database not initialized. Call initialize() or use as a context manager."
            )
        return self._conn

    def close(self) -> None:
        """Close the database connection if open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Database:
        """Open and initialize the database."""
        self.initialize()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Close the database connection."""
        self.close()
