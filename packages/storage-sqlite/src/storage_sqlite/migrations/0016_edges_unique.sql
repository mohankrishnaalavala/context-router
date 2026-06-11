-- Migration 0016: edge dedup (v4.6 A1 — DoD v4.6-edge-dedup).
--
-- The pydantic real-world validation showed 37.6% of edge rows were exact
-- duplicates of (repo, from_symbol_id, to_symbol_id, edge_type) — worst
-- case 161 identical `extends → BaseModel` rows from one test file.
-- Duplicate rows acted as implicit ranking weight via degree COUNT(*).
--
-- This migration rebuilds `edges` with a UNIQUE constraint over the
-- logical edge identity and collapses existing duplicates into a single
-- row carrying weight = SUM(weight), so the legitimate "references X many
-- times" signal survives as weight instead of row multiplicity. Degree
-- consumers switch from COUNT(*) to SUM(weight) in the same release.

CREATE TABLE edges_new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    repo           TEXT NOT NULL,
    from_symbol_id INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    to_symbol_id   INTEGER REFERENCES symbols(id) ON DELETE CASCADE,
    edge_type      TEXT NOT NULL,
    weight         REAL NOT NULL DEFAULT 1.0,
    UNIQUE (repo, from_symbol_id, to_symbol_id, edge_type)
);

INSERT INTO edges_new (repo, from_symbol_id, to_symbol_id, edge_type, weight)
SELECT repo, from_symbol_id, to_symbol_id, edge_type, SUM(weight)
FROM edges
GROUP BY repo, from_symbol_id, to_symbol_id, edge_type;

DROP TABLE edges;
ALTER TABLE edges_new RENAME TO edges;

-- Recreate the indexes the old table carried (0001, 0008, 0010).
CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_repo_from ON edges(repo, from_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_repo_to ON edges(repo, to_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_repo_type ON edges(repo, edge_type);

INSERT OR REPLACE INTO schema_version(version) VALUES (16);
