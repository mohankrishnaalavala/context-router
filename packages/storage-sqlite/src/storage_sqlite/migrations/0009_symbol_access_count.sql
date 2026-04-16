-- Migration 0009: add access_count to symbols for selection-frequency signal.

ALTER TABLE symbols ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE symbols ADD COLUMN last_accessed_at TEXT;

INSERT OR REPLACE INTO schema_version(version) VALUES (9);
