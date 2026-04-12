# ADR-0001: Use SQLite + FTS5 as the only storage backend in v1

**Status:** Accepted  
**Date:** 2024-01

## Context

context-router must store symbols, dependency edges, observations, decisions,
and runtime signals locally. It needs full-text search across observations
and decisions. The product must work with zero internet access and no external
services. We considered:

- PostgreSQL + pgvector
- DuckDB
- SQLite + FTS5
- A flat-file store (JSON/CSV)

## Decision

Use SQLite with FTS5 (via Python's built-in `sqlite3` module) as the only
storage backend in v1.

## Consequences

**Positive:**
- Zero external dependencies — ships as pure Python with no install-time setup
- FTS5 provides full-text search sufficient for observations and decisions
- WAL mode allows concurrent reads during indexing
- Migrations are simple sequential SQL files; no ORM required
- Widely available on all platforms; no Docker required

**Negative:**
- Not suitable for multi-user or cloud scenarios (explicitly out of scope for v1)
- FTS5 token estimation is not model-aware (acceptable; we use char/line heuristics)
- No vector similarity search — semantic ranking must be deferred or optional

**Out of scope:** Vector databases, cloud sync, and PostgreSQL are explicitly
non-goals for v1. They may be added as optional backends in a future version.
