-- Migration 0001: initial schema
-- Creates all tables, indexes, and FTS5 virtual tables.

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS symbols (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    repo      TEXT NOT NULL,
    file_path TEXT NOT NULL,
    name      TEXT NOT NULL,
    kind      TEXT NOT NULL,
    line_start INTEGER,
    line_end   INTEGER,
    language   TEXT,
    signature  TEXT,
    docstring  TEXT
);

CREATE INDEX IF NOT EXISTS idx_symbols_repo_file ON symbols(repo, file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);

CREATE TABLE IF NOT EXISTS edges (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    repo           TEXT NOT NULL,
    from_symbol_id INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    to_symbol_id   INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    edge_type      TEXT NOT NULL,
    weight         REAL NOT NULL DEFAULT 1.0
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_symbol_id);

CREATE TABLE IF NOT EXISTS observations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    task_type     TEXT,
    summary       TEXT,
    files_touched TEXT,   -- JSON array
    commands_run  TEXT,   -- JSON array
    failures_seen TEXT,   -- JSON array
    fix_summary   TEXT,
    commit_sha    TEXT,
    repo_scope    TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    -- Uses SQLite's implicit rowid for FTS5 content_rowid.
    -- id stores the UUID string; rowid is the integer primary key.
    id           TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'proposed',
    context      TEXT,
    decision     TEXT,
    consequences TEXT,
    tags         TEXT,    -- JSON array
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_signals (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    source    TEXT,
    severity  TEXT NOT NULL DEFAULT 'error',
    message   TEXT,
    stack     TEXT,   -- JSON array
    paths     TEXT,   -- JSON array
    timestamp TEXT NOT NULL
);

-- FTS5 virtual tables for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
    summary,
    fix_summary,
    content='observations',
    content_rowid='id'
);

CREATE VIRTUAL TABLE IF NOT EXISTS decisions_fts USING fts5(
    title,
    context,
    decision,
    content='decisions',
    content_rowid='rowid'
);

-- Seed schema version
INSERT OR IGNORE INTO schema_version(version) VALUES (1);
