-- Migration 0003: add task_hash to observations for deduplication
-- task_hash is a short SHA256 of (task_type + summary[:80]) used by the
-- auto-capture guardrail to prevent duplicate observations for the same task.
ALTER TABLE observations ADD COLUMN task_hash TEXT NOT NULL DEFAULT '';

INSERT OR REPLACE INTO schema_version(version) VALUES (3);
