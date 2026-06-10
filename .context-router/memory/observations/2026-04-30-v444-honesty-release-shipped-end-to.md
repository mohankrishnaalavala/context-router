---
id: 2026-04-30-v444-honesty-release-shipped-end-to
type: observation
task: implement
files_touched:
  - benchmark/run-holdout.sh
  - benchmark/run-comparison.sh
  - benchmark/build_k8s_synthetic.sh
  - benchmark/holdout/kubernetes/tasks.yaml
  - benchmark/README.md
  - benchmarks/comparison-code-review-graph.md
  - benchmarks/results/2026-04-29-k8s-comparison/summary.json
  - packages/storage-sqlite/src/storage_sqlite/migrations/0015_symbols_fts.sql
  - packages/storage-sqlite/src/storage_sqlite/repositories.py
  - packages/storage-sqlite/tests/test_symbols_fts.py
  - packages/core/src/core/orchestrator.py
  - packages/core/tests/test_implement_fts_anchor.py
  - CHANGELOG.md
  - docs/release/v4-outcomes.yaml
  - apps/cli/pyproject.toml
  - apps/mcp-server/pyproject.toml
  - packages/*/pyproject.toml
created_at: 2026-04-30T14:15:56.551430+00:00
author: context-router
---

v4.4.4 "Honesty release" shipped end-to-end across one session — tag v4.4.4, GitHub release, PyPI, Homebrew published.

Resumed an interrupted plan in `.handover/work/v4.4.4-plan.md`. Phase 1 (agent docs cleanup, [all-languages] extra, graph viz fix) was already on develop unpushed; pushed it. Phase 2 added --anchor flag (fix-sha / parent-sha-with-diff / query-only) to benchmark/run-holdout.sh with anchor stamped in score JSON + summary, plus k8s/tasks.yaml fixture (initially placeholders). Phase 4 (FTS5 implement-mode anchor) ran in a parallel worktree subagent: new external-content FTS5 virtual table on (name, signature, file_path) with porter+unicode61, three triggers, seeded via INSERT INTO symbols_fts(symbols_fts) VALUES ('rebuild'), SymbolRepository.search_fts(query, repo, limit=200), Orchestrator._implement_candidates unions FTS top-200 with get_all 10K slice. Phase 3 (k8s SHAs + CRG comparison) ran in a second parallel worktree subagent: synthetic k8s repo built from per-commit GitHub tarballs because partial-clone and depth-50000 throttled, picked 3 single-source-file SHAs (kubelet status_manager, client-go clientcmd loader, kube-proxy/winkernel proxier), ran 9 holdout configs + CRG comparison. Phase 5 bumped 27 packages 4.4.3→4.4.4, wrote CHANGELOG and 4 DoD entries, opened PR #118, tag pushed after merge, Release workflow succeeded in 14m18s. Final headline: ~88% fewer tokens vs code-review-graph on workload-matched k8s (replaces v4.4.3's cross-workload 91.5% claim).
