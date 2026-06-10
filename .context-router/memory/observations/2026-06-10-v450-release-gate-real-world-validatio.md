---
id: 2026-06-10-v450-release-gate-real-world-validatio
type: observation
task: implement
files_touched:
  - benchmarks/realworld-pydantic-13215.md
created_at: 2026-06-10T19:17:34.332231+00:00
author: context-router
---

v4.5.0 release-gate real-world validation PASSED: pydantic issue #13215 (pre-fix checkout a20c0ee) — GT file _generics.py rank 3/37 with exact fix function create_generic_submodel lines 105-149; ~5.3k tokens e2e vs 94.8k naive baseline (~94.5% reduction); full feature sweep PASS (index 7.85s/15.6k symbols, doctor 0% vendored, graph 500 real nodes, MCP 17 tools, memory, explain). PR #120 merged to main (5675b4e); validation report at benchmarks/realworld-pydantic-13215.md via PR #121. 892MB stale .claude/worktrees removed. v4.6 findings: get_all 10k cap hits internal callers on >10k-symbol repos; duplicate edges from same-named local classes (161x extends BaseModel); edge-count reporting mismatch (27,915 reported vs 24,253 DB rows); CLI pack JSON emits both items and selected_items while MCP emits only selected_items. Title-only queries miss GT when fix file lacks symptom keywords — semantic re-rank is the designed answer.
