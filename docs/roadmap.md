# context-router Roadmap
<!-- Last updated: 2026-06-10 · v4.5.0 shipped · v4.6.0 in progress -->

---

## In progress: v4.6.0 — Hands-Free Context

**Design spec:** [`docs/design/v4.6-hands-free-context.md`](design/v4.6-hands-free-context.md) · **DoD:** `docs/release/v4-outcomes.yaml` ids `v4.6-*`

Phase A — graph accuracy (edge dedup + weight semantics, scope-qualified
symbol identity, edge-count consistency, full-set ranking past the 10k cap,
ground-truth edge precision/recall audit). Phase B — auto-fresh index
(pack-time staleness self-heal, `hooks install` for Claude Code).

Split decision (2026-06-10): auto-save observations + memory health and the
localhost savings dashboard moved to **v4.7.0** ("visible memory"). Plan:
`docs/superpowers/plans/2026-06-10-v4.6-roadmap.md`.

---

## Shipped: v4.5.0 ✅ (2026-06-10) — Trustworthy Context

Index hygiene (20 default ignore patterns, doctor check), real graph
rendering (+ `--json -o` fix), end-to-end token benchmark, retrieval
re-baseline (F1 0.613). Release-gated on a real-world validation: pydantic
issue #13215, ground-truth file rank 3/37, ~94.5% end-to-end token
reduction ([report](../benchmarks/realworld-pydantic-13215.md)).

---

## Shipped: v4.4.5 ✅ (2026-05-30)

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

## v4.7.0 — Visible Memory (planned, not started)

Split out of the v4.6 plan (2026-06-10). Scope per
`docs/superpowers/plans/2026-06-10-v4.6-roadmap.md` Phases C + D:

- **Auto-save observations** — `hooks install` adds a SessionEnd hook →
  `memory capture --auto` (derived from git diff + recent pack queries; a
  floor, not a replacement for hand-written observations)
- **Memory health in `doctor`** — warns when commits outpace observations;
  provenance mix; orphaned files_touched ratio
- **Local savings dashboard** — `pack_events` telemetry table +
  `context-router dashboard` (stdlib http.server, localhost-only)

Still unscheduled: `pack-content-by-default`, workspace semantic opt-in,
multi-repo federation (deferred by user decision 2026-06-10).
