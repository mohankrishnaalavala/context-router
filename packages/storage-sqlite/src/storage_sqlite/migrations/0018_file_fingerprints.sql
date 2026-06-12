-- Migration 0018: per-file freshness fingerprints (v4.6 B1 —
-- DoD v4.6-pack-staleness-selfheal).
--
-- The indexer records one (mtime_ns, size) row per successfully indexed
-- file so the orchestrator can detect index drift at pack time with one
-- batched read + an os.stat per file — no content re-hash on the fresh
-- path. Files indexed before this migration have no rows; the
-- orchestrator emits a named WARN ("no freshness fingerprints") until the
-- next full `context-router index` backfills them.

CREATE TABLE IF NOT EXISTS file_fingerprints (
    repo TEXT NOT NULL,
    file_path TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL,
    PRIMARY KEY (repo, file_path)
);

INSERT OR REPLACE INTO schema_version(version) VALUES (18);
