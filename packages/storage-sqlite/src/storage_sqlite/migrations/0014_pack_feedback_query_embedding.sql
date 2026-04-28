-- Migration 0014: Add query_text and query_embedding columns to
-- pack_feedback. Used by v4.4.2 Phase 6 (query-conditional feedback)
-- to cosine-weight historical adjustments by query similarity.
--
-- Both columns are nullable: legacy rows and rows recorded without a
-- query (or when sentence-transformers is unavailable) keep NULL and
-- the read path falls back to v4.4.1 unweighted behaviour.

ALTER TABLE pack_feedback ADD COLUMN query_text TEXT NULL;
ALTER TABLE pack_feedback ADD COLUMN query_embedding BLOB NULL;
