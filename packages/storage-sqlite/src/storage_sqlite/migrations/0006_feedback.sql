-- Agent feedback for context packs (Phase 6)
-- Stores what was useful, missing, or noisy so pack ranking can improve over time.

CREATE TABLE IF NOT EXISTS pack_feedback (
    id            TEXT PRIMARY KEY,
    pack_id       TEXT NOT NULL,
    useful        INTEGER DEFAULT NULL,          -- 1=yes, 0=no, NULL=not rated
    missing       TEXT NOT NULL DEFAULT '[]',    -- JSON array of file/symbol paths
    noisy         TEXT NOT NULL DEFAULT '[]',    -- JSON array of file/symbol paths
    too_much_ctx  INTEGER NOT NULL DEFAULT 0,
    reason        TEXT NOT NULL DEFAULT '',
    timestamp     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_pack ON pack_feedback(pack_id);

INSERT OR REPLACE INTO schema_version(version) VALUES (6);
