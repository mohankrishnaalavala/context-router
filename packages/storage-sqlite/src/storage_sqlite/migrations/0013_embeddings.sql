-- Migration 0013: persistent embeddings table for proactive semantic ranking.
--
-- Without this table, `pack --with-semantic` re-encodes every candidate symbol
-- on every invocation (~10× slower than a lexical-only pack). The embed CLI
-- subcommand populates this table once per repo so subsequent semantic packs
-- become a pure cosine lookup against pre-computed vectors.
--
-- Vectors are stored as packed float32 BLOBs (np.array(...).astype(np.float32)
-- .tobytes()), not JSON — for all-MiniLM-L6-v2 that is 384 × 4 = 1536 bytes
-- per row, an order of magnitude smaller than a JSON-encoded float list.

CREATE TABLE IF NOT EXISTS embeddings (
    repo       TEXT    NOT NULL,
    symbol_id  INTEGER NOT NULL,
    model      TEXT    NOT NULL,            -- e.g. 'all-MiniLM-L6-v2'
    vector     BLOB    NOT NULL,            -- packed float32 array
    built_at   REAL    NOT NULL,            -- unix epoch seconds
    PRIMARY KEY (repo, symbol_id, model),
    FOREIGN KEY (symbol_id) REFERENCES symbols(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_embeddings_repo ON embeddings(repo);

INSERT OR REPLACE INTO schema_version(version) VALUES (13);
