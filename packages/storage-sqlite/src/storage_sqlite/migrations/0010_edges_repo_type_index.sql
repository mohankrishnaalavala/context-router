-- Migration 0010: composite index on edges(repo, edge_type).
-- Lane C (P3-4) — fixes the full-table scan flagged in the Apr 15 review
-- when BFS traversals filter edges by (repo, edge_type='calls').

CREATE INDEX IF NOT EXISTS idx_edges_repo_type ON edges(repo, edge_type);

INSERT OR REPLACE INTO schema_version(version) VALUES (10);
