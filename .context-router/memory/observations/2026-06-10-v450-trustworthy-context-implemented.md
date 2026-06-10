---
id: 2026-06-10-v450-trustworthy-context-implemented
type: observation
task: implement
files_touched:
  - packages/contracts/src/contracts/config.py
  - packages/graph-index/src/graph_index/scanner.py
  - packages/graph-index/src/graph_index/indexer.py
  - packages/storage-sqlite/src/storage_sqlite/repositories.py
  - apps/cli/src/cli/commands/doctor.py
  - apps/cli/src/cli/commands/graph.py
  - apps/mcp-server/src/mcp_server/tools.py
  - benchmark/judge_packs.py
  - BENCHMARKS.md
  - README.md
  - CHANGELOG.md
created_at: 2026-06-10T18:14:20.564280+00:00
author: context-router
---

v4.5.0 "Trustworthy Context" implemented end-to-end on develop via subagent-driven execution of docs/superpowers/plans/2026-06-09-v4.5-release.md. Shipped: gitignore-aware dir-pruned scanner (pathspec), hardened ignore defaults (+*.min.js/*.min.css), self-healing index prune (with zero-eligible guard AND external-stub exclusion — ship-check smoke caught that prune wiped kind='external' inheritance stubs, fix fa28a1c restored implements/extends), doctor pollution check (+fresh-env fix), get_all ORDER BY+cap warn, graph ignored-path filter + --json -o, embeddings_enabled config honored, MCP workspace TypeError fix, semantic re-rank reverted to opt-in (ablation: default-on costs -0.076 F1). Results: own repo 48,970→2,880 symbols (0% vendored); F1 0.394→0.613 (beats v3.3.0 0.577); e2e benchmark n=21/7 repos: 15,325 vs CRG 380,260 tokens (-96%), rank1 21/21 vs 16/21. Judge (claude-fable-5) FAILED on credit balance — judge_sufficient_rate=null, re-run benchmark/judge_packs.py when credits available. Smoke: 27 PASS, 7 pre-existing FAILs, 0 new. UPGRADE CAVEAT: user config.yaml ignore_patterns REPLACES defaults — documented in CHANGELOG. Stale-venv-shadowing landmine: literal copies in .venv/site-packages shadow editable installs; cleaned all 16 this session.
