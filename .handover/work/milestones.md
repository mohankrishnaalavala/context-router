# Milestones
<!-- Last updated: 2026-06-10 · v4.4.5 shipped · v4.5.0 in progress -->

Phases 0–8 are complete (public release baseline). Phases 9–13 (v4.0–v4.4) are released. v4.5.0 is in progress on `develop`.

---

## Milestone 0 — Repo Foundation ✅
**Goal:** Clean skeleton, all contracts defined, CLI stub working, tests passing.
**Exit gate:** `context-router --help` works; all packages import cleanly; smoke tests pass.

## Milestone 1 — Single-Repo Indexer ✅
**Goal:** Index any Python, Java, .NET, or YAML repo and store symbols/edges/tests.
**Exit gate:** `context-router index` completes on sample repos for all 4 languages.

## Milestone 2 — Context Packs v1 ✅
**Goal:** Ranked, explainable packs for review and implement modes.
**Exit gate:** Packs return smaller estimated token counts than naive baseline on all sample repos.

## Milestone 3 — Debug Layer ✅
**Goal:** Debug packs that outperform graph-only baseline using runtime evidence.
**Exit gate:** Debug pack beats graph-only baseline on 3 of 5 sample debug tasks.

## Milestone 4 — Memory and Handover ✅
**Goal:** Durable observations and decisions surfaced in packs and handover output.
**Exit gate:** Memory and decisions appear in packs; handover pack produces valid delivery summary.

## Milestone 5 — MCP Server ✅
**Goal:** Live agent tool calls from Claude Code to local MCP server.
**Exit gate:** Claude Code successfully calls `get_context_pack` and receives a valid ContextPack.

## Milestone 6 — Agent Adapters ✅
**Goal:** Claude, Copilot, and Codex can consume router output without manual editing.
**Exit gate:** Each adapter produces correct output files; Copilot custom agent files are schema-valid.

## Milestone 7 — Multi-Repo Workspace ✅
**Goal:** 3-repo workspace indexes and returns labelled cross-repo packs.
**Exit gate:** Feature and debug flows demonstrated end-to-end across 3 repos.

## Milestone 8 — Benchmarks and Public Release ✅
**Goal:** Reproducible benchmark results published; v0.1.0 released.
**Exit gate:** Real benchmark numbers published in README; v0.1.0 tagged.

---

## Milestone 9 — v4.0: Evaluation & Workspace DB ✅ (2026-04-23)
**Goal:** Continuous recall quality gate in CI; workspace edges pre-built so cross-repo packs never recompute at query time.

**Delivered:**
- `context-router eval --queries <path> --json` — Recall@K / Precision@K / F1@K harness
- `context-router workspace sync` — writes cross-repo edges to `.context-router/workspace.db`
- Synthetic fixture (10 queries) + CI gate enforcing Recall@20 ≥ 0.65 on every PR
- `WorkspaceOrchestrator.cross_repo_edges_for_repo()` — reads from workspace.db, no recompute

**Exit gate:** `scripts/eval-synthetic.sh` exits 0 with "PASS synthetic-recall-gate".

---

## Milestone 10 — v4.1: Memory-as-Code ✅ (2026-04-24)
**Goal:** Observations become git-tracked Markdown files — reviewable, diffable, shareable via normal git workflows.

**Delivered:**
- `save_observation` dual-writes: SQLite (primary) + `.context-router/memory/observations/{date}-{slug}.md`
- Write gate rejects observations with summary < 60 chars or empty `files_touched`; warns to stderr
- `pack --use-memory` / MCP `use_memory: true` — injects up to 8 BM25+recency-ranked hits into every pack
- `memory migrate-from-sqlite` — backfills existing SQLite observations to `.md` files
- `memory show <id>` — observation lookup by exact or prefix ID
- License changed to Apache 2.0

**Exit gate:** `scripts/smoke-v4.1.sh` passes 4/4.

---

## Milestone 11 — v4.2: Memory Quality ✅ (2026-04-24)
**Goal:** Memory in packs is token-budget-controlled, provenance-aware, and precision-optimized.

**Delivered:**
- Memory sub-budget cap: memory items ≤ 15% of total token budget; configurable via `memory_budget_pct`; out-of-range values warn to stderr and fall back to 0.15
- Adaptive top-k: items with confidence < 0.6× leader dropped in `review`/`implement` modes; `debug`/`handover` return all budget-admitted items
- Observation provenance: `MemoryHit.provenance` classifies as `committed` / `staged` / `branch_local` via `git ls-files`; non-committed observations filtered from main-branch packs
- `budget: {total_tokens, memory_tokens, memory_ratio}` in all `--json` pack outputs
- `memory_hits_summary: {committed, staged}` added alongside `memory_hits` in JSON output
- Fixed test-file conditional penalty regression introduced in v4.1

**Exit gate:** `scripts/smoke-v4.2.sh` passes 4/4.

---

## Milestone 12 — v4.3: Staleness & Federation ⏭ (superseded)
**Goal:** Stale observations surfaced and prunable; cross-repo memory federation.

**Status:** This milestone was planned but not shipped. Its scope was reviewed in 2026-05 and split: the most critical work (index hygiene, graph trustworthiness) was reprioritised into v4.5.0. Staleness detection and cross-repo federation remain in the backlog.

---

## Milestone 13 — v4.4: Symbol Packs + Language Expansion ✅ (2026-04-29)
**Goal:** Agents receive actual code bodies (not file pointers); 10-language coverage; honest benchmark comparison.

**Delivered:**
- `symbol_body` field in `ContextItem` — top-ranked symbol's source text injected into every pack
- Six new language analyzers (Go, Rust, Ruby, PHP, SQL, and YAML improvements)
- FTS5-anchored implement-mode candidates (BM25-ranked `symbols_fts` virtual table; handles >10K-symbol repos)
- Three holdout suites (A: gin/actix-web, B: gson/requests/zod, C: kubernetes) with reproducible anchors
- Workload-matched competitor comparison vs `code-review-graph` at identical SHAs (~88% fewer tokens)
- v4.4.4 honesty release: FTS5 anchor, correct benchmark framing, implement-mode regression fix
- v4.4.5 packaging hotfix: drop unpublished `context-router-evaluation` dep; issue-reporting docs

**Exit gates:**
- v4.4.4: `scripts/smoke-v4.4.sh` passes; benchmark summary committed at `benchmarks/results/`
- v4.4.5: clean-machine `uv tool install context-router-cli` succeeds

---

## Milestone 14 — v4.5: Trustworthy Context 🔄 (in progress)
**Goal:** Index never ingests vendored code; `context-router graph` renders own-code symbols; token claims are end-to-end; retrieval F1 re-baselined.

**Planned deliverables:**
- `ignore_patterns` expanded to 20 defaults (`.venv*`, `node_modules`, `vendor`, `dist`, `build`, `target`, `site-packages`, `*.min.js`, `*.min.css`, and more); gitignore-aware scanner pruning
- `SymbolRepository.get_all` ordered and capped with a loud stderr warning; ignored-path filter on graph nodes
- `graph --json -o <file>` writes the file (was a silent no-op)
- End-to-end benchmark: pack tokens + downstream read tokens + model-judge sufficiency across n ≥ 12 tasks
- Retrieval re-baseline after hygiene: F1 0.613 (up from 0.394 pre-hygiene; see `docs/eval/2026-06-10-v4.5-phase-c-rebaseline.md`)
- Docs currency sweep across `.handover/`, `docs/`, README

**Exit gate:** `scripts/smoke-v4.5.sh` passes all gates; BENCHMARKS.md updated with end-to-end figures.
