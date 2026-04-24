# context-router Roadmap
<!-- Last updated: 2026-04-24 · v4.2.0 current -->

---

## Current: v4.2.0 ✅ (2026-04-24)

Memory quality release. Shipped: memory sub-budget cap (15%), adaptive top-k confidence pruning, observation provenance (`committed`/`staged`/`branch_local`), `budget.memory_ratio` in all JSON outputs. See [CHANGELOG](../CHANGELOG.md) for full details.

---

## Next: v4.3 — Staleness & Federation

**Design spec:** [`docs/design/v4.3-staleness-federation.md`](design/v4.3-staleness-federation.md)

**Two outcomes:**

1. **Staleness detection** — `memory stale` lists observations whose `files_touched` paths are gone from HEAD. Stale hits in pack output carry `"stale": true` with a stderr warning. `memory prune --stale` removes them.

2. **Memory federation** — `search_memory --workspace` and `pack --use-memory --workspace` query memory across all repos in `workspace.yaml`. Only committed observations federate. Each hit carries `source_repo`.

**Ship gate:** `scripts/smoke-v4.3.sh` — all gates pass.

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
| v4.2.0 | Memory quality (sub-budget, adaptive top-k, provenance) | 2026-04-24 |
| v4.1.0 | Memory-as-code (git-tracked .md observations, --use-memory) | 2026-04-24 |
| v4.0.0 | Evaluation harness, workspace.db, Recall@20 CI gate | 2026-04-23 |
| v3.3.1 | Hotfix: MCP server crash on fresh pip install | 2026-04-20 |
| v3.3.0 | First-run fix, default pack size, MCP progress notifications | 2026-04-20 |
| v3.2.x | FastAPI/CRG evaluation, adapter polish | 2026-04-18 |
| v3.1.x | Copilot custom agents, multi-repo workspace | 2026-04-17 |
| v3.0.0 | Public release, benchmark harness, all 4 languages | 2026-04-18 |
