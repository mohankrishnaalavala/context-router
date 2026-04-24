# Implementation Tasks
<!-- Last updated: 2026-04-24 · Phases 0–11 complete · v4.3 is next -->

Phases 0–8 and v4.0–v4.2 (Milestones 9–11) are fully shipped. This file tracks only open and upcoming work.

---

## Phase 12 — v4.3: Staleness & Federation

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

## Backlog (post-v4.3)

These are not scheduled but are captured so they are not lost:

- SSE transport for MCP server (remote/cloud Copilot agent scenarios)
- Vector embedding opt-in for semantic memory search (keyless fallback to BM25 must remain)
- `context-router doctor` output machine-readable flag `--json` for CI integration
- Observation quality scoring: auto-flag low-signal observations at write time (short fix_summary, no commands_run)
- GitHub Actions workflow that auto-runs `memory prune --stale` on a schedule
