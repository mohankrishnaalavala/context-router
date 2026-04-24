# Constraints & Non-Goals
<!-- Last updated: 2026-04-24 · Updated for v4.2 state -->

Hard requirements and explicit non-goals — what we must do, and what we are deliberately not doing.

---

## Hard Constraints

- Core product must work with no API key and no internet connection
- No source code upload by default; all data stays local
- Secrets must be masked before any content is written to memory or logs
- SQLite is the primary storage backend; no vector DB, no PostgreSQL
- No business logic in CLI or MCP server app layers; both are thin shells over `core`
- No adapter may call language analyzers directly; all calls go through core interfaces
- Language analyzers must return normalized contracts, never raw Tree-sitter nodes
- Storage must only be accessed through repository interfaces
- Every `ContextItem` in a pack must include `reason`, `confidence`, and `est_tokens`
- Multi-repo context packs must label every item with its source repo name
- Every `--json` pack output must include `budget: {total_tokens, memory_tokens, memory_ratio}`
- Any flag, mode, or tool that has no effect in a given context MUST warn to stderr with a named reason — no silent no-ops

## Quality Constraints

- Every user-visible feature must have an entry in the version outcomes YAML (`docs/release/v4-outcomes.yaml`) before the PR merges
- Every feature spec must fill all four DoD fields (`outcome`, `threshold`, `negative_case`, `verify`) before implementation begins
- CLI flags and MCP tool signatures are stable across patch versions; breaking changes require a semver major bump
- The synthetic recall gate (Recall@20 ≥ 0.65) must pass on every PR

---

## Non-Goals

- Cloud sync or hosted service
- Team collaboration or shared workspaces beyond git-tracked memory files
- Vector database or semantic embeddings as the primary search path (may be added as an optional layer)
- Browser or desktop UI
- More than 3 agent adapters (Claude, Copilot, Codex)
- More than 4 languages (Python, Java, C#/.NET, YAML) without a plugin contribution
- More than 3 repos in a workspace
- Autonomous PR merging or code execution on behalf of the user
- Real-time multi-user index sharing
- IDE plugin as a primary surface (MCP covers this use case)
