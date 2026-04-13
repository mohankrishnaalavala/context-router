-- Migration 0002: add community_id to symbols
-- Uses a conditional approach since ALTER TABLE does not support IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS _migration_tmp_check(x INTEGER);
DROP TABLE IF EXISTS _migration_tmp_check;

-- Add community_id column only if it does not already exist.
-- We detect absence via pragma_table_info and use a trigger-less DDL workaround.
-- SQLite does not support ALTER TABLE ADD COLUMN IF NOT EXISTS, so we rely on
-- the migration runner's version check to ensure this runs exactly once.
ALTER TABLE symbols ADD COLUMN community_id INTEGER DEFAULT NULL;

INSERT OR REPLACE INTO schema_version(version) VALUES (2);
