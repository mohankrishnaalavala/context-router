-- Migration 0012: pack_cache — persistent L2 cache for ranked ContextPack
-- results so that repeated `context-router pack` CLI invocations survive
-- process exits. (v2.0.0 shipped an in-process TTLCache that only benefited
-- the long-lived MCP server; CLI runs never hit.)
--
-- cache_key   — stable sha1 over (mode, query, budget, use_embeddings,
--               items_hash). Composed in Python; the DB does not parse it.
-- repo_id     — sha1(db_mtime || repo_name). Any re-index bumps the DB's
--               mtime, which in turn bumps the repo_id, which in turn makes
--               the row invisible to subsequent lookups. Belt-and-suspenders
--               invalidation additionally runs an explicit DELETE on index.
-- pack_json   — ContextPack.model_dump_json() payload; read back via
--               ContextPack.model_validate_json(...).
-- inserted_at — unix epoch float. TTL enforced on read, mirroring the
--               in-process TTLCache's 300s default.

CREATE TABLE IF NOT EXISTS pack_cache (
  cache_key   TEXT NOT NULL,
  repo_id     TEXT NOT NULL,
  pack_json   TEXT NOT NULL,
  inserted_at REAL NOT NULL,
  PRIMARY KEY (cache_key, repo_id)
);

CREATE INDEX IF NOT EXISTS idx_pack_cache_repo ON pack_cache(repo_id);

INSERT OR REPLACE INTO schema_version(version) VALUES (12);
