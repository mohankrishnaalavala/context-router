-- Migration 0004: memory freshness + decision supersession
--
-- Observations gain three freshness fields:
--   confidence_score  — 0-1 editorial quality rating (default 0.5)
--   access_count      — how many times the observation appeared in a context pack
--   last_accessed_at  — ISO timestamp of the most recent pack appearance
--
-- Decisions gain three fields:
--   confidence        — 0-1 editorial confidence in the decision (default 0.8)
--   last_reviewed_at  — ISO timestamp of last manual review
--   superseded_by     — UUID of the decision that replaces this one

ALTER TABLE observations ADD COLUMN confidence_score REAL NOT NULL DEFAULT 0.5;
ALTER TABLE observations ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE observations ADD COLUMN last_accessed_at TEXT DEFAULT NULL;

ALTER TABLE decisions ADD COLUMN confidence REAL NOT NULL DEFAULT 0.8;
ALTER TABLE decisions ADD COLUMN last_reviewed_at TEXT DEFAULT NULL;
ALTER TABLE decisions ADD COLUMN superseded_by TEXT DEFAULT NULL;

INSERT OR REPLACE INTO schema_version(version) VALUES (4);
