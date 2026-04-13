-- Debug memory fields for runtime_signals (Phase 4)
--   error_hash    — SHA256[:16] of normalized exception type + message
--                   enables exact-match recall when the same error recurs
--   top_frames    — JSON array of {"file","function","line"} for top 5 frames
--   failing_tests — JSON array of failing test names (from JUnit XML)

ALTER TABLE runtime_signals ADD COLUMN error_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE runtime_signals ADD COLUMN top_frames TEXT NOT NULL DEFAULT '[]';
ALTER TABLE runtime_signals ADD COLUMN failing_tests TEXT NOT NULL DEFAULT '[]';

CREATE INDEX IF NOT EXISTS idx_signals_error_hash ON runtime_signals(error_hash)
    WHERE error_hash != '';

INSERT OR REPLACE INTO schema_version(version) VALUES (5);
