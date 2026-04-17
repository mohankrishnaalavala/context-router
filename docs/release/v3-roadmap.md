# v3.0.0 roadmap

> Living tracker for the v3 release. Every row maps to an outcome id in
> [`v3-outcomes.yaml`](./v3-outcomes.yaml). The roadmap, the registry,
> and the smoke script are the three source-of-truth documents — keep
> them consistent. See [`README.md`](./README.md) for the full process.

## Status legend

- ⬜ not started
- 🟨 in progress (branch cut, agent/owner assigned)
- 🟧 in review (PR open against `develop`)
- ✅ landed on `develop` and smoke PASS
- 🔒 locked on `main` (ready for v3.0.0 tag)

## Rollup

| Phase | Outcomes | Done / Total | Target |
|---|---|---|---|
| 0 · Scaffolding | docs/release, ship-check skill, smoke script | ✅ 1/1 | 2026-04-17 |
| 1 · First impressions | cli-version, dedup, interface-kind, semantic-warning, ci-develop | ⬜ 0/5 | 2026-04-24 |
| 2 · Speed & discoverability | cache persistence, proactive embeddings, semantic default, contracts boost | ⬜ 0/4 | 2026-05-01 |
| 3 · CRG-parity intelligence | edge kinds, enums, hub/bridge, minimal-context, call-chain, risk, untested | ⬜ 0/7 | 2026-05-15 |
| 4 · Advanced features + MCP polish | flow-level, wiki, streaming, coupling, mimeType, serverInfo, ci95 | ⬜ 0/7 | 2026-05-29 |
| Release | v3.0.0 tag after 23/23 smoke PASS + full 7-prompt re-review | ⬜ | 2026-05-30 |

---

## Phase 0 · Scaffolding ✅ (2026-04-17)

Set up the quality gate so nothing ships without it.

| id | status | notes |
|---|---|---|
| `docs/release/*`, smoke, skill, `/ship-check`, CLAUDE.md policy | ✅ | Baseline: 1 PASS / 22 FAIL on `main` (expected). |

---

## Phase 1 · First impressions

Goal: a first-time user does not see an obvious bug in the first 60 seconds.

| id | sev | effort | status | branch | PR | owner |
|---|---|---|---|---|---|---|
| `cli-version-flag` | P0 | S | ⬜ | `phase1/cli-version-flag` | — | agent-A |
| `pack-table-dedup` | P0 | S | ⬜ | `phase1/pack-table-dedup` | — | agent-B |
| `interface-kind-label` | P0 | S | ⬜ | `phase1/interface-kind-label` | — | agent-C |
| `with-semantic-warns-outside-implement` | P1 | S | ⬜ | `phase1/with-semantic-warns` | — | agent-D |
| `benchmark-develop-ci` | P1 | S | ⬜ | `phase1/benchmark-develop-ci` | — | agent-E |

**Parallelism:** 5 isolated worktrees, zero file overlap. See "Conflict-free file map" below.

**Phase gate (before Phase 2 starts):**
- All 5 PRs merged to `develop`.
- `scripts/smoke-v3.sh check <id>` PASS for all 5.
- 7-prompt re-review prompts 1, 3, 7 (competitive gap, ranking quality, ship-readiness) run against the Phase 1 diff. Reports in `internal_docs/ship-check/per-phase-reviews/phase-1/`.

---

## Phase 2 · Speed & discoverability

Goal: v2.0 half-shipped features (cache, semantic, contracts, progress) actually deliver.

| id | sev | effort | status |
|---|---|---|---|
| `pack-cache-persists-cli` | P1 | S | ⬜ |
| `proactive-embedding-cache` | P2 | M | ⬜ |
| `semantic-default-with-progress` | P2 | S | ⬜ |
| `contracts-boost-single-repo` | P1 | M | ⬜ |

**Lanes:** A (cache → proactive-embedding, sequential) ‖ B (semantic + contracts, parallel).
**Phase gate:** all 9 Phase 1+2 outcomes PASS. Re-review prompts 2 (algorithmic efficiency) + 6 (benchmark).

---

## Phase 3 · CRG-parity intelligence

Goal: close every column where `code-review-graph` currently leads.

| id | sev | effort | dep |
|---|---|---|---|
| `edge-kinds-extended` | P3 | M | interface-kind-label |
| `enum-symbols-extracted` | P3 | S | — |
| `hub-bridge-ranking-signals` | P2 | M | edge-kinds |
| `get-minimal-context-tool` | P2 | S | — |
| `call-chain-symbols-mcp` | P2 | M | — |
| `review-mode-risk-score` | P3 | S | — |
| `audit-untested-hotspots` | P3 | M | edge-kinds (TESTED_BY) |

**Lanes:** A (edges → hub/bridge → untested, sequential) ‖ B (minimal-context + call-chain + risk-score, parallel).
**Phase gate:** all 16 outcomes PASS. Re-review prompts 1 (competitive gap) + 5 (language analyzers).

---

## Phase 4 · Advanced features & MCP polish

Goal: ceiling-raising features. Any slippage here is additive, not a blocker.

| id | sev | effort |
|---|---|---|
| `flow-level-debug` | P3 | L |
| `handover-wiki` | P3 | L |
| `mcp-pack-streams-large` | P2 | L |
| `cross-community-coupling` | P3 | S |
| `mcp-mimetype-content` | P2 | S |
| `mcp-serverinfo-version` | P2 | S |
| `benchmark-ci-emits-ci95` | P1 | S |

**Lanes:** A (flows → wiki) ‖ B (streaming MCP) ‖ C (3 small MCP polish items, parallel).
**Phase gate:** 23/23 PASS. Full 7-prompt playbook one last time before tagging `v3.0.0`.

---

## Conflict-free file map (Phase 1)

Zero-overlap contract for the 5 Phase 1 agents:

| agent | outcome | files the agent may write | files it must NOT touch |
|---|---|---|---|
| A | cli-version-flag | `apps/cli/src/cli/main.py`, `apps/cli/tests/test_version.py` (new) | anything else |
| B | pack-table-dedup | `apps/cli/src/cli/commands/pack.py` (only `_print_pack` + test hook), `apps/cli/tests/test_pack_dedup.py` (new) | `main.py`, `ranker.py`, language-* |
| C | interface-kind-label | `packages/language-java/src/**`, `packages/language-dotnet/src/**`, tests under both | CLI, core, ranker |
| D | with-semantic-warns | `packages/ranking/src/ranking/ranker.py`, `packages/ranking/tests/` | CLI, core, language-* |
| E | benchmark-develop-ci | `.github/workflows/ci.yml` | everything else |

**Shared-file rule.** If an agent discovers it needs to edit a file in another
agent's scope, it must STOP and surface the dependency — never silently edit
across scopes. The parent coordinates resolution.

**Non-scope edits forbidden for all agents.** No edits to `v3-outcomes.yaml`,
`smoke-v3.sh`, `CLAUDE.md`, `docs/release/*`, or `pyproject.toml` version
fields during Phase 1. Any such change comes back as a follow-up PR after
Phase 1 closes.

---

## Agent contract (applies to every phase)

Every agent:

1. Runs in an isolated git worktree cut from the current tip of `develop`.
2. Creates its branch per the table above.
3. Edits ONLY files listed in its row of "Conflict-free file map".
4. Writes or updates tests alongside the code change. All tests must pass before opening the PR.
5. Runs `scripts/smoke-v3.sh check <outcome-id>` locally. Must PASS.
6. Runs `scripts/smoke-v3.sh report` — captures the smoke report path. Does **not** worry about unrelated FAILs; only the outcome this branch implements must flip to PASS.
7. Opens a PR to `develop` with the ship-check verdict block pasted into the body (see `.claude/skills/ship-check/SKILL.md` §5).
8. Never commits to `v3-outcomes.yaml`, `smoke-v3.sh`, `CLAUDE.md`, `docs/release/*`, or files outside its row in the scope table.

## Rebase hygiene

- Phase 1's 5 PRs all target `develop`. The first PR to merge is the new base; the remaining 4 rebase (`git rebase origin/develop`) before CI re-runs.
- No force-push to `develop` or `main`. Force-push on a feature branch requires an explicit user OK.
- If a merge conflict appears on rebase, the agent stops and surfaces the conflict — no auto-resolve that silently discards the other side's changes.
