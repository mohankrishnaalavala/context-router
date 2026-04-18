# v3.1.0 hotfix roadmap

Queued from the v3.0.0 post-release audit — see
[`internal_docs/production-readiness-review-v3.md`](../../internal_docs/production-readiness-review-v3.md)
for full findings.

## Rollup

| # | Outcome id | Severity | Effort | Scope | Lane |
|---|---|---|---|---|---|
| 1 | `homebrew-tap-v3` | P0 | S (external) | Update tap repo + regen sha256 | external (user action) |
| 2 | `benchmark-keyword-baseline-honest` | P0 | S | Remove clamp at `packages/benchmark/src/benchmark/reporters.py:103`; fix `vs_keyword` column so negative deltas are visible | A |
| 3 | `typescript-inheritance-edges` | P1 | M | Extend `packages/language-typescript/src/language_typescript/__init__.py` to emit `extends`/`implements`/`tested_by` on function-component + JSX test patterns (bulletproof-react 0-edge gap) | B |
| 4 | `contracts-boost-tighter-match` | P1 | S | Anchor the URL-regex in `packages/contracts-extractor/src/contracts_extractor/matching.py` so generic verbs like "create order" don't match every POST endpoint | C |
| 5 | `minimal-mode-ranker-tuning` | P1 | S | Adjust `Orchestrator._build_minimal_mode` weights so top implement-mode result survives the ≤5 cap on task-verb queries | D |
| 6 | `readme-mcp-tool-count` | P1 | XS | Already landed in chore/v3.1-docs as part of this roadmap PR | — |
| 7 | `hub-bridge-smoke-query` | P2 | S | Replace the BM25-dominated query in `scripts/smoke-v3.sh` with one where the top-5 is structurally-sensitive so the +0.10 boost can flip positions | E |
| 8 | `flows-n-plus-one` | P2 | S | Cache `_callees(symbol_id)` in `packages/graph-index/src/graph_index/flows.py` BFS to eliminate the N+1 round-trip | F |
| 9 | `hub-bridge-sqlite-reuse` | P2 | S | Reuse the existing `Orchestrator._db.connection` in `_apply_hub_bridge_boost` instead of opening a fresh connection per pack | G |

**Release target:** `v3.1.0` — 2026-04-25 (one-week cadence, all items S/M).

## Phase layout

Two parallel waves, then release PR.

### Wave 1 (5 agents in parallel, zero file overlap)

| Agent | Outcome | Files |
|---|---|---|
| A | `benchmark-keyword-baseline-honest` | `packages/benchmark/src/benchmark/{reporters,harness,models}.py`, tests |
| B | `typescript-inheritance-edges` | `packages/language-typescript/src/language_typescript/__init__.py`, tests |
| C | `contracts-boost-tighter-match` | `packages/contracts-extractor/src/contracts_extractor/matching.py`, tests |
| D | `minimal-mode-ranker-tuning` | `packages/core/src/core/orchestrator.py` (minimal-mode branch only), tests |
| E | `hub-bridge-smoke-query` | `scripts/smoke-v3.sh` (`_check_hub-bridge-ranking-signals` only) |

### Wave 2 (2 agents in parallel after Wave 1 merges)

| Agent | Outcome | Files |
|---|---|---|
| F | `flows-n-plus-one` | `packages/graph-index/src/graph_index/flows.py`, tests |
| G | `hub-bridge-sqlite-reuse` | `packages/ranking/src/ranking/ranker.py` (hub-bridge boost path only), tests |

### External (user action)

- `homebrew-tap-v3`: copy `docs/homebrew-formula.rb` to
  `github.com/mohankrishnaalavala/homebrew-context-router:Formula/context-router.rb`,
  regen sha256 for 3.0.0 tarball.

## Agent contract (same as v3 phases)

- Worktree isolation, branch `v3.1/<outcome-id>`, cut from `origin/develop`.
- Ship-check verdict block in every PR body.
- No edits to `v3-outcomes.yaml` / `smoke-v3.sh` except the one handler
  owned by that agent.
- Silent-failure rule: any new user-visible change that could be a no-op
  MUST emit stderr.

## Gate

Release `v3.1.0` when all 6 in-repo items land (#1 ships on tap-repo cadence, can publish after CLI release). Final smoke: 24/24 on coordinator with `sentence-transformers` installed; 22/24 acceptable in CI-lite environments (the 2 env-gated semantic outcomes).
