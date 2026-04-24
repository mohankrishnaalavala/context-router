# Acceptance Criteria — Definition of Done
<!-- Last updated: 2026-04-24 · Phases 0–11 complete · v4.3 criteria added -->

---

## Phase 0 Done ✅
- Monorepo folder structure matches architecture spec
- `contracts` package contains all shared Pydantic schemas with no business logic
- CLI shell runs `context-router --help` without error
- SQLite schema bootstraps on `context-router init`
- All package boundaries are clean (no cross-module direct imports)
- pytest harness runs with at least one passing test per package

## Phase 1 Done ✅
- `context-router index` completes on a Python, Java, .NET, and YAML sample repo
- Symbols and dependency edges written to SQLite
- Test file mapping works for pytest, JUnit, and xUnit patterns
- Incremental update triggered by file-save event via watchdog

## Phase 2 Done ✅
- `context-router pack --mode review --query "..."` returns a ranked ContextPack
- `context-router pack --mode implement --query "..."` returns a ranked ContextPack
- Every item includes `reason`, `confidence`, and `est_tokens`
- `context-router explain last-pack` prints human-readable selection rationale
- Estimated token count is lower than naive baseline on all sample repos

## Phase 3 Done ✅
- Debug pack ingests pytest XML, JUnit XML, dotnet test output, and raw stack traces
- `context-router pack --mode debug` returns items ranked by runtime signal match
- Debug pack outperforms graph-only baseline on 3 of 5 sample debug tasks

## Phase 4 Done ✅
- Observations can be stored and searched via CLI
- Decisions can be stored and retrieved
- `search_memory` MCP tool returns relevant prior observations
- Stale memory is flagged when files referenced no longer exist

## Phase 5 Done ✅
- `context-router mcp` starts a local stdio MCP server
- All 8 v1 MCP tools respond correctly to test calls
- Claude Code can call `get_context_pack` and receive a valid ContextPack

## Phase 6 Done ✅
- Claude adapter generates usable task prompts from ContextPack
- Copilot adapter generates `.github/copilot-instructions.md` and `.github/agents/*.agent.md`
- Codex adapter generates compatible subagent/task prompt artifacts

## Phase 7 Done ✅
- `workspace.yaml` with 3 repos loads and indexes correctly
- Cross-repo pack labels every item with source repo
- One feature flow and one debug flow demonstrated across 3 repos

## Phase 8 Done ✅
- Benchmark harness runs all 20 sample tasks and produces JSON reports
- README contains a real benchmark table with actual measured numbers
- Demo repos for Python, Java, and multi-repo are included in the repository
- First public release candidate tagged

---

## v4.0 Done ✅ (2026-04-23)
- `context-router eval --queries <path> --json` emits valid JSON with `recall_at_k`, `k`, `n_queries`, `mean_pack_tokens`, `token_efficiency`, `per_query`
- `context-router eval --queries /nonexistent.jsonl` exits non-zero with a stderr message naming the missing file
- `context-router workspace sync` on the synthetic fixture completes without error and prints a TOTAL line to stdout
- Running `workspace sync` without `workspace.yaml` prints a warning to stderr and exits non-zero
- `scripts/eval-synthetic.sh` exits 0 with "PASS synthetic-recall-gate" on the current codebase
- `WorkspaceOrchestrator.cross_repo_edges_for_repo()` reads from workspace.db; returns empty list when workspace.db does not exist (no error)

## v4.1 Done ✅ (2026-04-24)
- After `save_observation`, a `.md` file exists under `.context-router/memory/observations/` with YAML frontmatter listing `files_touched`
- `save_observation` with no `files_touched` does not write a `.md` file; emits explicit stderr warning
- `save_observation` with `summary < 60 chars` does not write; emits explicit stderr warning
- `pack --use-memory --json` output contains `memory_hits` key (≥ 0 items; no crash when memory is empty)
- `pack` without `--use-memory` does not include `memory_hits` key
- `memory migrate-from-sqlite` writes one `.md` file per valid SQLite row; skips rows failing the write gate
- `scripts/smoke-v4.1.sh` passes 4/4

## v4.2 Done ✅ (2026-04-24)
- Memory items in a pack never exceed `int(total_budget × 0.15)` tokens (default cap)
- `budget.memory_ratio` is present in all `--json` pack outputs as a float in `[0.0, 0.15]`
- Setting `memory_budget_pct ≤ 0` or `≥ 1` in config.yaml emits a stderr warning and falls back to 0.15
- In `review`/`implement` modes, no returned item has `confidence < 0.6 × items[0].confidence`
- In `debug`/`handover` modes, all budget-admitted items are returned regardless of confidence spread
- When all items have similar confidence (spread < 40%), no items are dropped
- `MemoryHit.provenance` is one of `committed`, `staged`, `branch_local`
- On `main`, non-committed observations do not appear in pack output
- `memory_hits_summary: {committed, staged}` present in `--json` output alongside `memory_hits`
- `scripts/smoke-v4.2.sh` passes 4/4

---

## v4.3 Done (criteria for next release)
- `memory stale` lists all observations whose `files_touched` paths are absent from HEAD; output includes path, severity, and age
- `memory prune --stale` removes stale observations and prints a count to stdout; `--archive` moves them instead of deleting
- Stale hits in `search_memory` output carry `"stale": true` and a `staleness_reason` in stderr warning
- When graph index is behind the last commit, `pack` emits a stderr warning naming the lag
- `search_memory --workspace` returns hits from all sibling repos labeled with `source_repo`
- `pack --use-memory --workspace` injects federated hits; `memory_hits_summary` includes `federated` count
- `scripts/smoke-v4.3.sh` passes all gates
