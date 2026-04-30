-- Migration 0015: FTS5 virtual table over symbols for implement-mode anchoring.
--
-- Phase 4 of v4.4.4: implement-mode on >10K-symbol repos with no diff anchor
-- previously returned noise because SymbolRepository.get_all caps at 10,000
-- rows with no ORDER BY. This migration adds a BM25-ranked FTS5 index over
-- (name, signature, file_path) so the orchestrator can recall a focused
-- top-N candidate set that is unioned with the truncated 10K slice.
--
-- The plan called the second column "qualified_name" — the symbols table has
-- no such column, so we index `signature` instead, which carries the
-- qualified context (e.g. "class Manager.unprepareResources(...)") that
-- analyzers emit for methods. Using an existing column keeps the trigger
-- pattern simple and avoids a schema break.
--
-- The standard SQLite "external content" pattern is used: the FTS table
-- mirrors the indexed columns of the `symbols` base table (content_rowid
-- defaults to the base rowid, which is `symbols.id` because that column is
-- INTEGER PRIMARY KEY AUTOINCREMENT). Three triggers keep the index live.

CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    signature,
    file_path,
    content='symbols',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Insert: mirror the new row into FTS.
CREATE TRIGGER IF NOT EXISTS symbols_ai
AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, signature, file_path)
    VALUES (new.id, new.name, COALESCE(new.signature, ''), new.file_path);
END;

-- Delete: emit the FTS5 'delete' command which removes the row by rowid.
CREATE TRIGGER IF NOT EXISTS symbols_ad
AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, signature, file_path)
    VALUES ('delete', old.id, old.name, COALESCE(old.signature, ''), old.file_path);
END;

-- Update: delete the old FTS row, then insert the new one.
CREATE TRIGGER IF NOT EXISTS symbols_au
AFTER UPDATE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, signature, file_path)
    VALUES ('delete', old.id, old.name, COALESCE(old.signature, ''), old.file_path);
    INSERT INTO symbols_fts(rowid, name, signature, file_path)
    VALUES (new.id, new.name, COALESCE(new.signature, ''), new.file_path);
END;

-- Seed: populate the FTS index from any pre-existing rows so the migration
-- does not require a full re-index on already-indexed repos. With external
-- content tables, `INSERT INTO ... SELECT` does NOT actually build the FTS
-- index — it only inserts content references that the engine already infers
-- from the base table. The canonical seed for an external-content FTS5
-- table is the `'rebuild'` command, which scans the base table and writes
-- the inverted index. Safe to run on an empty base table (no-op).
INSERT INTO symbols_fts(symbols_fts) VALUES ('rebuild');

INSERT OR IGNORE INTO schema_version(version) VALUES (15);
