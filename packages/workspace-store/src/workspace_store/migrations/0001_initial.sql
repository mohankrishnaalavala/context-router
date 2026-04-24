-- workspace.db schema (ADR §7.4). Cross-repo artefacts ONLY.

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS repo_registry (
  repo_id TEXT PRIMARY KEY,
  repo_name TEXT NOT NULL,
  repo_root TEXT NOT NULL,
  last_indexed_at TEXT,
  per_repo_db_mtime REAL
);

CREATE TABLE IF NOT EXISTS cross_repo_edges (
  id INTEGER PRIMARY KEY,
  src_repo_id TEXT NOT NULL,
  src_symbol_id INTEGER,
  src_file TEXT NOT NULL,
  dst_repo_id TEXT NOT NULL,
  dst_symbol_id INTEGER,
  dst_file TEXT NOT NULL,
  edge_kind TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (src_repo_id) REFERENCES repo_registry(repo_id) ON DELETE CASCADE,
  FOREIGN KEY (dst_repo_id) REFERENCES repo_registry(repo_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cross_edges_src ON cross_repo_edges(src_repo_id, edge_kind);
CREATE INDEX IF NOT EXISTS idx_cross_edges_dst ON cross_repo_edges(dst_repo_id, edge_kind);
CREATE INDEX IF NOT EXISTS idx_cross_edges_src_file ON cross_repo_edges(src_repo_id, src_file);

INSERT OR REPLACE INTO schema_version(version) VALUES (1);
