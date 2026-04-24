# Decision Log (ADRs)
<!-- Last updated: 2026-04-24 · ADR-001 through ADR-013 -->

Architecture Decision Records. Each entry captures status, context, decision, and consequences.

---

## ADR-001: Python as implementation language

**Status:** Active

**Decision:** Use Python 3.12+ for all core packages.

**Reason:** Best ecosystem fit for Tree-sitter bindings, SQLite, MCP server, CLI tooling, and test/log parsers. Fastest delivery path. Easiest OSS contribution ramp.

**Consequences:** Performance-critical paths (large repo scanning) may need profiling; async where needed.

---

## ADR-002: Contracts package as the only cross-module interface

**Status:** Active

**Decision:** All shared types (ContextItem, ContextPack, Observation, RuntimeSignal, LanguageAnalyzer, Ranker, AgentAdapter) live exclusively in `packages/contracts` with no business logic.

**Reason:** Enforces loose coupling. Any module can be replaced without touching others. Prevents circular imports.

**Consequences:** Slightly more boilerplate at boundaries; payoff is full replaceability.

---

## ADR-003: SQLite + FTS5 as the primary storage backend

**Status:** Active

**Decision:** Use SQLite with FTS5 for all persistence: symbols, edges, memory, observations, decisions, runtime signals. `workspace.db` is a separate SQLite file at workspace root for cross-repo edges.

**Reason:** Zero-dependency local storage. FTS5 gives full-text search without a vector DB. Sufficient for target scale. Avoids cloud dependency.

**Non-goal:** No vector DB, no cloud sync, no PostgreSQL.

---

## ADR-004: MCP as the primary agent integration protocol

**Status:** Active

**Decision:** Expose all agent-facing capabilities through an MCP server with local stdio transport as the default.

**Reason:** MCP is supported by Claude Code, GitHub Copilot (IDE/CLI/cloud), and Codex-style agent workflows. One server serves all three agent targets without maintaining separate APIs.

**Consequences:** Agent adapters become thin translation layers over MCP tool outputs.

---

## ADR-005: Deterministic ranking first, LLM optional

**Status:** Active

**Decision:** The ranking engine produces useful output using only deterministic signals (structural relevance, recency, test proximity, runtime signal match, cross-repo edge strength). LLM-assisted summarization is an optional, flagged enhancement.

**Reason:** Keeps the core product offline, keyless, fast, and benchmarkable. Avoids depending on an external model call for basic function.

---

## ADR-006: Language support via pluggable analyzer modules

**Status:** Active

**Decision:** Each language is a separate package (`language-python`, `language-java`, `language-dotnet`, `language-yaml`) implementing the `LanguageAnalyzer` interface. Core has no language-specific knowledge.

**Reason:** New languages can be added by creating a new package without modifying core, ranking, or storage.

---

## ADR-007: Multi-repo as a first-class workspace model

**Status:** Active

**Decision:** The workspace abstraction (`workspace.yaml` + `packages/workspace`) is designed into the architecture from Phase 0. `workspace.db` pre-builds cross-repo edges via `workspace sync`.

**Reason:** Retrofitting multi-repo into a single-repo data model is expensive. Designing `RepoDescriptor` and `WorkspaceDescriptor` contracts early avoids breaking changes later.

---

## ADR-008: No API key required for core product

**Status:** Active

**Decision:** All indexing, ranking, context pack generation, memory storage, and MCP serving work with zero external API calls.

**Reason:** Maximizes OSS adoption. Eliminates cost/privacy friction for new users. Makes benchmarking reproducible.

**Consequences:** Optional provider integrations (embeddings, summarization) are explicitly opt-in and documented as such.

---

## ADR-009: Memory-as-code via git-tracked Markdown files

**Status:** Active · Introduced in v4.1

**Decision:** `save_observation` dual-writes to SQLite (primary query store) and a git-tracked `.md` file under `.context-router/memory/observations/{date}-{slug}.md` with YAML frontmatter.

**Reason:** Git-tracked memory is reviewable in PRs, diffable, and portable across machines via normal git workflows. SQLite remains the query engine for speed; `.md` files are the source of truth for sharing.

**Consequences:** Write gate is mandatory (summary ≥ 60 chars, non-empty `files_touched`) to prevent low-signal observations from polluting the git history. `memory migrate-from-sqlite` provides a one-time backfill path.

---

## ADR-010: Evaluation harness as a first-class CI gate

**Status:** Active · Introduced in v4.0

**Decision:** Recall@K evaluation runs on every PR via `scripts/eval-synthetic.sh`. PRs that drop Recall@20 below 0.65 on the synthetic fixture are blocked.

**Reason:** v2.0.0 shipped with green unit tests but visible P0 ranking regressions. Outcome-based CI gates prevent algorithm changes from silently degrading pack quality.

**Consequences:** Every ranking change must be validated against the synthetic fixture. New fixtures should be added when new ranking modes are introduced.

---

## ADR-011: Memory sub-budget enforcement at 15%

**Status:** Active · Introduced in v4.2

**Decision:** Memory and decision items in a context pack are capped at `int(total_budget × memory_budget_pct)` tokens, defaulting to 15%. Configurable via `.context-router/config.yaml`. Values ≤ 0 or ≥ 1 warn to stderr and fall back to 0.15.

**Reason:** Uncapped memory injection degrades code context quality by filling the token budget with observations rather than relevant source files. A 15% cap ensures memory enriches without dominating.

**Consequences:** `budget.memory_ratio` is always present in `--json` output so downstream tooling can observe actual memory consumption.

---

## ADR-012: Observation provenance via git ls-files

**Status:** Active · Introduced in v4.2

**Decision:** Each `MemoryHit` carries a `provenance` field (`committed` / `staged` / `branch_local`) derived from `git ls-files --error-unmatch` and `git diff --cached --name-only`. On the `main` branch, non-committed observations are filtered from packs to preserve teammate isolation.

**Reason:** Memory-as-code means observation files go through the same git lifecycle as code. Surfacing provenance lets agents distinguish peer-reviewed memory (committed) from in-progress observations (staged/branch_local).

**Consequences:** `git` must be available at pack time for provenance classification. When git is unavailable, all hits are treated as `committed` (no crash, no empty pack).

---

## ADR-013: Adaptive top-k via confidence-spread pruning

**Status:** Active · Introduced in v4.2

**Decision:** In `review` and `implement` modes, items with `confidence < 0.6 × items[0].confidence` are dropped after budget enforcement. `debug` and `handover` modes return all budget-admitted items regardless of relative confidence.

**Reason:** Low-confidence trailing items degrade precision without meaningfully improving recall. The 0.6 threshold was tuned against the judge benchmark to restore F1 ≥ 0.45 in review mode (up from 0.270 baseline). Debug and handover modes need completeness over precision.

**Consequences:** When all items have similar confidence (spread < 40%), no items are dropped. When only one item survives, it is always returned regardless of its absolute confidence value.
