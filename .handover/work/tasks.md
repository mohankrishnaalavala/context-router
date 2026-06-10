# Implementation Tasks
<!-- Last updated: 2026-06-10 · v4.4.x shipped · v4.5.0 in progress on develop -->

Phases 0–8 and v4.0–v4.4 (Milestones 9–13) are fully shipped. This file tracks only open and upcoming work.

**Shipped:**
- v4.4.4 (2026-04-29) — Honesty release: FTS5 implement-mode anchor, workload-matched CRG comparison
- v4.4.5 (2026-05-30) — Packaging hotfix: drop unpublished `context-router-evaluation` dep, issue-reporting docs

**In progress on `develop`:**
- v4.5.0 "Trustworthy Context" — index hygiene (shipped to develop), graph fixes, e2e benchmark, docs sweep
- Design spec: [`docs/design/v4.5-trustworthy-context.md`](../../docs/design/v4.5-trustworthy-context.md)

---

## v4.5.0 — Trustworthy Context (in progress)

### Workstream 1 — Index hygiene ✅ (shipped to develop)

- [x] Expand `ignore_patterns` default in `packages/contracts/src/contracts/config.py` to 20 patterns (`.venv*`, `venv`, `env`, `.tox`, `.nox`, `node_modules`, `vendor`, `dist`, `build`, `target`, `__pycache__`, `.git`, `*.egg-info`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `site-packages`, `*.min.js`, `*.min.css`)
- [x] Add `context-router doctor` check for stale indexed paths matching ignore patterns
- [x] Index-time prune: DELETE rows whose `file_path` matches ignore patterns on incremental runs

### Workstream 2 — Graph trustworthiness

- [ ] Add `ORDER BY file_path` and stderr warning when symbol query is capped in `SymbolRepository.get_all`
- [ ] Add ignored-path filter to graph node selection (drop vendored nodes, warn count)
- [ ] Fix `graph --json -o <file>`: write JSON to `<file>` when `-o` supplied; error on missing parent dir

### Workstream 3 — End-to-end token benchmark

- [ ] Extend `benchmarks/judge_packs.py` to record `downstream_read_tokens` per task
- [ ] Add model-judge step using `claude` CLI (sufficient? yes/no + reason per task)
- [ ] Run on n ≥ 12 holdout tasks across ≥ 4 repos (at least one new repo)
- [ ] Update `BENCHMARKS.md` headline to report end-to-end tokens + sufficiency rate

### Workstream 4 — Retrieval quality re-baseline + docs currency

- [ ] Retrieval re-baseline against 12-task tuning set post index-hygiene (F1 0.613 — see `docs/eval/2026-06-10-v4.5-phase-c-rebaseline.md`)
- [ ] Docs sweep: version currency across `.handover/`, `docs/`, and `apps/cli/README.md`

### Smoke gate

- [ ] Write `scripts/smoke-v4.5.sh` covering: index hygiene, graph correctness, e2e benchmark, F1 gate
- [ ] CI: add `smoke-v4.5` job

---

## Phase 12 — v4.3: Staleness & Federation (skipped — superseded by v4.5 scope)

### Staleness detection

- [ ] Implement `ObservationStalenessChecker`: for each observation, check whether each path in `files_touched` exists in HEAD via `git ls-files --error-unmatch`
- [ ] Classify staleness severity: `missing_file` (path not in HEAD at all) vs `old_commit` (observation commit > 30 days behind HEAD)
- [ ] Add `is_stale: bool` and `staleness_reason: str | None` fields to `MemoryHit` contract
- [ ] Surface stale warnings in `search_memory` output: print `WARN: observation <id> may be stale (<reason>)` to stderr when a hit is stale
- [ ] Add `stale` flag to pack `memory_hits` JSON: each hit includes `"stale": false` by default
- [ ] Implement `memory stale` CLI command: list all stale observations with path, severity, and age
- [ ] Implement `memory prune --stale` CLI command: delete (or `--archive` to move to `.context-router/memory/archived/`) all stale observations; print count to stdout
- [ ] Add DoD entry to `docs/release/v4-outcomes.yaml` for `v4.3-stale-detection`
- [ ] Stale index warning: compare `graph-index` mtime to `git log -1 --format=%ct HEAD`; emit stderr warning if index is > 1 commit behind

### Memory federation (workspace mode)

- [ ] Extend `MemoryRetriever` to accept an optional `workspace_root` path
- [ ] When `workspace_root` is set, discover sibling repo `.context-router/memory/observations/` directories from `workspace.yaml`
- [ ] Federated `search_memory`: merge BM25+recency results across all workspace repos; label each hit with `source_repo`
- [ ] Add `--workspace` flag to `pack --use-memory` to enable federated injection
- [ ] Extend `memory_hits_summary` JSON key: `{committed, staged, federated}` where `federated` counts cross-repo hits
- [ ] Add DoD entry to `docs/release/v4-outcomes.yaml` for `v4.3-memory-federation`

### Smoke gate

- [ ] Write `scripts/smoke-v4.3.sh` covering: stale detection, prune command, cross-repo search, federated pack injection
- [ ] Add 2 DoD entries in `docs/release/v4-outcomes.yaml` (staleness + federation)
- [ ] CI: add `smoke-v4.3` job wired to the new script

---

## Backlog (post-v4.5)

These are not scheduled but are captured so they are not lost:

- SSE transport for MCP server (remote/cloud Copilot agent scenarios)
- Vector embedding opt-in for semantic memory search (keyless fallback to BM25 must remain)
- `context-router doctor` output machine-readable flag `--json` for CI integration
- Observation quality scoring: auto-flag low-signal observations at write time (short fix_summary, no commands_run)
- GitHub Actions workflow that auto-runs `memory prune --stale` on a schedule
