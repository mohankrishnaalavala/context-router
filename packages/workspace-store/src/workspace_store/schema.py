"""Apply workspace.db migrations."""
from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

_MIGRATIONS = files("workspace_store").joinpath("migrations")


def current_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row[0] if row else 0
    except sqlite3.OperationalError:
        return 0


def apply_migrations(conn: sqlite3.Connection) -> int:
    for mig in sorted(_MIGRATIONS.iterdir(), key=lambda p: p.name):
        if not mig.name.endswith(".sql"):
            continue
        version = int(mig.name.split("_", 1)[0])
        if version > current_version(conn):
            conn.executescript(mig.read_text())
            conn.commit()
    return current_version(conn)


def open_workspace_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn)
    return conn
