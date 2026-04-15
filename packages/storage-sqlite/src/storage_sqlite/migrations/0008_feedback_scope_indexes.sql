-- Migration 0008: add feedback scoping plus hot-path indexes for P0 fixes.

ALTER TABLE pack_feedback ADD COLUMN repo_scope TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_feedback_repo_scope_timestamp
ON pack_feedback(repo_scope, timestamp);

CREATE INDEX IF NOT EXISTS idx_symbols_repo_name
ON symbols(repo, name);

CREATE INDEX IF NOT EXISTS idx_symbols_repo_community
ON symbols(repo, community_id);

CREATE INDEX IF NOT EXISTS idx_edges_repo_from
ON edges(repo, from_symbol_id);

CREATE INDEX IF NOT EXISTS idx_edges_repo_to
ON edges(repo, to_symbol_id);

INSERT OR REPLACE INTO schema_version(version) VALUES (8);
