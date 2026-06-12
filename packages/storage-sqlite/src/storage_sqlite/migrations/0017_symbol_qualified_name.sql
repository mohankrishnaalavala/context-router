-- Migration 0017: scope-qualified symbol identity (v4.6 A2 —
-- DoD v4.6-symbol-qualification).
--
-- Same-named symbols defined at different scopes in one file used to
-- collapse to a single identity during edge resolution (hundreds of
-- `class Model(BaseModel)` inside different pydantic test functions all
-- anchored their edges on one row). The writer now qualifies identity
-- with the enclosing parent-symbol chain (`test_a.Model`), stored here.
-- `name` keeps the short display name so FTS and by-name retrieval are
-- unchanged.

ALTER TABLE symbols ADD COLUMN qualified_name TEXT;

-- Backfill: pre-v4.6 rows have no scope information; their identity is
-- their short name until the next re-index recomputes the chain.
UPDATE symbols SET qualified_name = name WHERE qualified_name IS NULL;

-- Symbol identity churn invalidates every cached pack (migration 0012):
-- cached packs reference pre-qualification symbol identities and must be
-- discarded, never served stale. The migration runner emits the matching
-- stderr WARN (see _CACHE_INVALIDATING_VERSIONS in migrations.py).
DELETE FROM pack_cache;

INSERT OR REPLACE INTO schema_version(version) VALUES (17);
