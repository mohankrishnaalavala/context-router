# context-router Roadmap
<!-- Last updated: 2026-06-10 · v4.4.5 shipped · v4.5.0 in progress -->

---

## Current: v4.4.5 ✅ (2026-05-30)

Packaging hotfix. Drops the unpublished `context-router-evaluation` dep that broke clean-machine installs; adds issue-reporting docs (GitHub templates, SECURITY.md, CONTRIBUTING.md). See [CHANGELOG](../CHANGELOG.md) for full details.

---

## Shipped: v4.4.4 ✅ (2026-04-29)

Honesty release. FTS5-anchored implement-mode candidates for >10K-symbol repos; workload-matched comparison vs `code-review-graph` on identical SHAs and diffs (~88% fewer tokens, down from a cross-workload 91.5% claim in v4.4.3). Three holdout suites (gin/actix-web, gson/requests/zod, kubernetes).

---

## Shipped: v4.3 ✅ — merged into v4.4 scope

v4.3 staleness-detection and memory-federation scope was reviewed in 2026-05 and superseded: the more urgent correctness failures (index pollution, graph trustworthiness) were prioritised into v4.5.0. Staleness and federation remain in the backlog.

---

## Shipped: v4.2.0 ✅ (2026-04-24)

Memory quality release. Shipped: memory sub-budget cap (15%), adaptive top-k confidence pruning, observation provenance (`committed`/`staged`/`branch_local`), `budget.memory_ratio` in all JSON outputs.

---

## In progress: v4.5.0 — Trustworthy Context

**Design spec:** [`docs/design/v4.5-trustworthy-context.md`](design/v4.5-trustworthy-context.md)

**Four workstreams:**

1. **Index hygiene** ✅ shipped to `develop` — `ignore_patterns` expanded to 20 defaults (`.venv*`, `node_modules`, `vendor`, `dist`, `build`, `target`, `site-packages`, `*.min.js`, `*.min.css`, and more). Index-time prune, `doctor` check for stale paths.

2. **Graph trustworthiness** — `context-router graph` renders own-code symbols. `graph --json -o <file>` writes the file (was a silent no-op). Polluted index causes a named warning.

3. **End-to-end token benchmark** — Pack tokens + downstream read tokens + model-judge sufficiency across n ≥ 12 holdout tasks. Headline stat updated to end-to-end.

4. **Retrieval re-baseline** — Post-hygiene F1 0.613 (up from 0.394 pre-hygiene). See [`docs/eval/2026-06-10-v4.5-phase-c-rebaseline.md`](eval/2026-06-10-v4.5-phase-c-rebaseline.md).

**Ship gate:** `scripts/smoke-v4.5.sh` — all gates pass.

---

## v5.0 — Agent-native memory (vision, not scheduled)

The v4 series established memory as git-tracked markdown, with promotion, provenance, and federation. v5.0 would close the remaining gap: memory that survives refactors by anchoring to **symbol IDs** rather than file paths.

Concrete scope (not committed):
- `symbols_touched` frontmatter resolved to stable IDs (`repo::module::symbol::signature_hash`) at write time
- Renamed/moved symbols carry their ID — observations follow without user action
- Three-strike archive rule: observations excluded from 3 consecutive packs are auto-archived
- `memory health` command: corpus quality score across recency, coverage, and stale ratio

This is the "Semantic staleness" scope from the v4 design doc §6.2. It is deliberately deferred until the file-path staleness story (v4.3) is validated in production.

---

## Backlog (no release assigned)

| ID | Description | Why deferred |
|----|-------------|--------------|
| B1 | SSE transport for MCP server | Needed for remote/cloud Copilot agents; stdio covers 95% of use cases today |
| B2 | Vector embedding opt-in for memory search | BM25+recency covers recall well; embeddings would improve edge-case synonym matching |
| B3 | `context-router doctor --json` | Machine-readable output for CI integration; current human output is sufficient |
| B4 | Observation quality score at write time | Auto-flag low-signal observations (short fix_summary, no commands_run) |
| B5 | `memory prune --schedule` GitHub Action | Auto-prune stale observations on a cron; easy after v4.3 ships |
| B6 | LSP integration | Real-time symbol updates without manual `index` command |
| B7 | VS Code extension | One-click context insertion; MCP covers this adequately for now |

---

## Shipped history

| Version | Theme | Date |
|---------|-------|------|
| v4.4.5 | Packaging hotfix: clean-machine install, issue-reporting docs | 2026-05-30 |
| v4.4.4 | Honesty release: FTS5 anchor, workload-matched benchmark (~88% fewer tokens) | 2026-04-29 |
| v4.4.3 | Holdout regressions fixed; AGENT_GUIDE.md; BENCHMARKS.md | 2026-04-28 |
| v4.4.2 | symbol_body field; 6 new language analyzers; precision-first budgets | 2026-04-27 |
| v4.4.1 | Measurement baseline; downstream token counting | 2026-04-26 |
| v4.4.0 | Eval harness baseline; Phase A shipped | 2026-04-25 |
| v4.2.0 | Memory quality (sub-budget, adaptive top-k, provenance) | 2026-04-24 |
| v4.1.0 | Memory-as-code (git-tracked .md observations, --use-memory) | 2026-04-24 |
| v4.0.0 | Evaluation harness, workspace.db, Recall@20 CI gate | 2026-04-23 |
| v3.3.1 | Hotfix: MCP server crash on fresh pip install | 2026-04-20 |
| v3.3.0 | First-run fix, default pack size, MCP progress notifications | 2026-04-20 |
| v3.2.x | FastAPI/CRG evaluation, adapter polish | 2026-04-18 |
| v3.1.x | Copilot custom agents, multi-repo workspace | 2026-04-17 |
| v3.0.0 | Public release, benchmark harness, all 4 languages | 2026-04-18 |

---

## v4.6 candidates (not scheduled)

These features are excluded from v4.5 scope but are the leading candidates for v4.6:

- **Hook / passive interception mode** — watch editor events and auto-update the index without a manual `context-router index` call
- **`pack-content-by-default`** — return symbol bodies in packs without requiring `--with-symbols`; controlled by a config flag
- **Workspace semantic opt-in flag** — `--semantic-workspace` enables cross-repo embedding similarity for memory federation (BM25 remains the default)
