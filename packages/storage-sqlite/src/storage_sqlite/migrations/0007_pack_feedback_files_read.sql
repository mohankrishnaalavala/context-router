-- Migration 0007: Add files_read column to pack_feedback table.
-- Stores a JSON array of file paths that the agent actually consumed after
-- receiving the context pack, enabling read-coverage analytics.

ALTER TABLE pack_feedback ADD COLUMN files_read TEXT NOT NULL DEFAULT '[]';
