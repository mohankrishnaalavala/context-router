---
id: 2026-06-10-v45-release-plan-written-to-docssuperp
type: observation
task: handover
files_touched:
  - docs/superpowers/plans/2026-06-09-v4.5-release.md
  - apps/cli/src/cli/commands/graph.py
  - packages/graph-index/src/graph_index/scanner.py
  - packages/storage-sqlite/src/storage_sqlite/repositories.py
created_at: 2026-06-10T01:46:48.079907+00:00
author: context-router
---

v4.5 release plan written to docs/superpowers/plans/2026-06-09-v4.5-release.md. Graph bug diagnosed via Playwright: graph renders 500 nodes/1466 edges but ZERO project symbols — get_all(limit=10_000) unordered slice (repositories.py:537) of the 91%-venv-polluted index, top-500-by-degree all vendored (dnspython/docutils/fastmcp). Also: graph --json silently ignores -o. Docs audit (Explore agent): structure GOOD (27 pkgs, 38k LOC, justified), onboarding GOOD (no broken refs), docs currency BAD — README claims v4.4.3/91%, .handover+roadmap 46 days stale. v4.4 roadmap Phases A (downstream.py) and B (symbol_body, orchestrator.py:2386) already landed; Phase C (retrieval F1 fix) unshipped. Plan: Task 0 spec+DoD, T1 ignore defaults, T2 gitignore-aware pruned-walk scanner (pathspec), T3 index prune of stale symbols, T4 doctor pollution check, T5 get_all order+cap warn, T6 graph filter + --json -o, T7 reindex+verify, T8 Phase C, T9 e2e benchmark w/ claude-fable-5 judge (benchmark/judge_packs.py), T10 docs sweep, T11 release 4.5.0.
