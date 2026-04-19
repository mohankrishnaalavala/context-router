# v3.2.0 roadmap — "close the CRG gap, automate the release"

Queued from the **fastapi vs code-review-graph eval** (`project_context/fastapi/.eval_results/judge_summary.md`, 2026-04-19) plus two carry-overs from the v3.1 queue plus the three items previously deferred to v3.3 (user directive 2026-04-19: fix everything in v3.2, draft a fresh plan for v3.3 later).

## Why this release

The external eval scored context-router 71/150 vs code-review-graph 139/150 on three real fastapi commits. Caveats apply (the eval ran Homebrew 0.3.0, not PyPI 3.1.0, and CRG was handed `git diff HEAD~1` while CR was handed only a free-text query), but four of the five scoring dimensions have **real, fixable gaps** that cost us points even under a fair comparison.

On top of the quality work, we end the recurring manual-release toll by **automating the Homebrew tap bump** inside `release.yml`.

| Dimension | v3.1 score est. | v3.2 target | How we close it |
|---|---|---|---|
| Precision | 3-4/10 | 7/10 | Review-tail cutoff + `--top-k` + mode-mismatch warning + symbol-stub dedup |
| Recall | 10/10 | 10/10 | already tied |
| Token efficiency | 5/10 | 7-8/10 | Tail cutoff + stub dedup (498→~40 items on fastapi task 1) |
| Explanation | 4/10 | 8/10 | Function-level `reason` strings (symbol + line range) |
| Actionability | 5/10 | 8/10 | Top-K + function names + pre-fix review mode for CRG-comparable workflow |

**Realistic per-task: 27/50 → 40/50.** On a *fair* diff-less head-to-head (CRG also on `HEAD~1`), CR should flip to the winner.

## Rollup (10 items, zero deferred)

| # | Outcome id | Severity | Effort | Scope | Lane |
|---|---|---|---|---|---|
| 1 | `function-level-reason` | P0 | M | Replace generic `reason` ("Referenced in codebase") with symbol + line range ("Modified `OAuth2PasswordRequestForm.__init__` lines 59-159") on all pack items with a backing symbol | A |
| 2 | `mode-mismatch-warning` | P1 | XS | `pack --mode review` with no diff + a free-text query → stderr warning suggesting `--mode debug` | C |
| 3 | `reproducible-eval-harness` | P1 | M | Ship `eval/fastapi-crg/` so the CR vs CRG eval is regression-tested every release | F |
| 4 | `homebrew-tap-automation` | P0 | S | Replace manual tap update with a `homebrew-publish` job in `release.yml` driven by a `HOMEBREW_TAP_TOKEN` secret (one-time user setup) | H |
| 5 | `top-k-flag` | P2 | S | `--top-k N` in CLI + MCP inputSchema caps selected_items post-ranking | D |
| 6 | `symbol-stub-dedup` | P1 | S | Collapse near-duplicate symbol entries (e.g. 16× `def __init__(` stubs per changed class) into one representative item with a `duplicates_hidden` counter | S |
| 7 | `pre-fix-review-mode` | P2 | M | `pack --mode review --pre-fix <SHA>` computes a diff-less pre-commit pack so CR is directly comparable to CRG on "where would the bug be?" workflow | I |
| 8 | `review-tail-cutoff` | P1 | S | Drop `source_type=file` items with confidence < 0.3 when higher tiers fill the budget; `--keep-low-signal` escape hatch | B |
| 9 | `capabilities-hub-boost-cache-key` | P1 | XS | Include `capabilities.hub_boost` in pack_cache cache-key tuple (v3.1 carry-over) | E |
| 10 | `diff-aware-ranking-boost` | P2 | M | Boost items whose symbol lies on the blame trail of changed lines; new `packages/graph-index/src/graph_index/blame.py` | J |

**Release target:** `v3.2.0` — 2026-04-30 (4-5 working days; three parallel waves).

## Phase layout (three waves, zero file overlap inside each wave)

### Wave 1 (4 agents parallel)

| Agent | Outcome | Primary files |
|---|---|---|
| A | `function-level-reason` | `packages/core/src/core/orchestrator.py` (item-build paths only), `packages/contracts/src/contracts/models.py` (reason docstring), tests |
| C | `mode-mismatch-warning` | `apps/cli/src/cli/commands/pack.py` (validation), `apps/mcp-server/src/mcp_server/tools.py` (same check), tests |
| F | `reproducible-eval-harness` | **new** `eval/fastapi-crg/` (`README.md`, `run.sh`, `score.py`, `fixtures/tasks.yaml`); zero overlap |
| H | `homebrew-tap-automation` | `.github/workflows/release.yml` (new `homebrew-publish` job), `docs/homebrew-formula.rb` (parameterize version/sha256), `docs/release/homebrew-setup.md` (new, one-time PAT setup) |

### Wave 2 (3 agents parallel, after Wave 1 merges)

| Agent | Outcome | Primary files |
|---|---|---|
| D | `top-k-flag` | `apps/cli/src/cli/commands/pack.py` (rebased on C), `apps/mcp-server/src/mcp_server/tools.py` (inputSchema), tests |
| S | `symbol-stub-dedup` | `packages/ranking/src/ranking/ranker.py` (dedup pass helper), `packages/core/src/core/orchestrator.py` (invoke dedup before tail filter), `packages/contracts/src/contracts/models.py` (extend `duplicates_hidden`), tests |
| I | `pre-fix-review-mode` | `apps/cli/src/cli/commands/pack.py` (new `--pre-fix` flag), `packages/core/src/core/orchestrator.py` (pre-fix branch), tests |

### Wave 3 (3 agents parallel, after Wave 2 merges)

| Agent | Outcome | Primary files |
|---|---|---|
| B | `review-tail-cutoff` | `packages/core/src/core/orchestrator.py` (review-mode finalization — rebased on S), tests |
| E | `capabilities-hub-boost-cache-key` | `packages/core/src/core/orchestrator.py` (cache-key tuple only — single edit), tests for toggle hit/miss |
| J | `diff-aware-ranking-boost` | **new** `packages/graph-index/src/graph_index/blame.py`, `packages/ranking/src/ranking/ranker.py` (new boost hook), tests |

### Dependency ordering rationale

- W1 A/C/F/H touch disjoint trees.
- W2 D rebases on C (both in `pack.py`); S and I both touch `orchestrator.py` but in **different** branches of `build_pack` (S adds the dedup helper called from all modes; I adds a new mode branch). Mergeable as siblings with a final conflict check before W3.
- W3 B rebases onto S (review tail needs the deduped item set as input); E touches only the cache-key tuple (~5 lines); J is in a new module.

## Homebrew automation detail (Agent H)

The new `homebrew-publish` job in `release.yml`:

```yaml
homebrew-publish:
  name: Publish Homebrew Formula
  needs: [publish, github-release]
  runs-on: ubuntu-latest
  if: ${{ startsWith(github.ref, 'refs/tags/v') }}
  steps:
    - name: Check out tap repo
      uses: actions/checkout@v4
      with:
        repository: mohankrishnaalavala/homebrew-context-router
        token: ${{ secrets.HOMEBREW_TAP_TOKEN }}
        path: tap

    - name: Compute sha256 of release tarball
      id: sha
      run: |
        VERSION="${GITHUB_REF#refs/tags/v}"
        URL="https://github.com/mohankrishnaalavala/context-router/archive/refs/tags/v${VERSION}.tar.gz"
        SHA=$(curl -sL "$URL" | sha256sum | cut -d' ' -f1)
        echo "version=$VERSION" >> "$GITHUB_OUTPUT"
        echo "sha=$SHA" >> "$GITHUB_OUTPUT"
        echo "url=$URL" >> "$GITHUB_OUTPUT"

    - name: Update Formula/context-router.rb
      run: |
        cd tap
        python3 ../scripts/render_homebrew_formula.py \
          --template ../docs/homebrew-formula.rb \
          --version "${{ steps.sha.outputs.version }}" \
          --sha256  "${{ steps.sha.outputs.sha }}" \
          > Formula/context-router.rb

    - name: Commit + push
      run: |
        cd tap
        git config user.name  "github-actions[bot]"
        git config user.email "github-actions[bot]@users.noreply.github.com"
        git add Formula/context-router.rb
        git commit -m "chore(formula): bump to v${{ steps.sha.outputs.version }}"
        git push
```

**Your one-time setup** (captured in `docs/release/homebrew-setup.md`):
1. On GitHub → your tap repo → Settings → create a fine-grained PAT with `contents: write` scope, 1-year expiry.
2. On the `context-router` repo → Settings → Secrets → add `HOMEBREW_TAP_TOKEN` with that PAT.
3. Confirm the tap repo has a `Formula/` directory (create empty if missing).

After this, every `git push origin v<version>` ships PyPI + GH release + Homebrew tap, in one workflow.

## Agent contract (same as v3.1)

- Worktree isolation, branch `v3.2/<outcome-id>`, cut from `origin/develop`.
- Ship-check verdict block in every PR body.
- No edits to `v3-outcomes.yaml` / `smoke-v3.sh` except the one handler owned by that agent.
- Silent-failure rule: any new user-visible flag that could be a no-op MUST emit stderr.

## Ship-check delta vs v3.1

v3.1 baseline: 27 PASS / 2 FAIL on develop (2 env-gated on `sentence-transformers`).

v3.2 target: **37 PASS / 2 FAIL** on develop (10 new outcomes all passing; env-gated pair unchanged).

Hard-block criteria (unchanged):
- Any new P0 outcome FAIL → block release.
- Any silent no-op → block PR.
- New user-visible flag without a `v3-outcomes.yaml` entry → block PR.

## Validation plan

Once v3.2.0 lands, re-run the fastapi eval **against PyPI 3.2.0** (now also available via `brew install` on the freshly-bumped tap) and expect:

- Per-task score 40/50 ± 2 (up from 27/50 est. on v3.1, 23/50 measured on 0.3.0).
- A *fair* rerun (CRG on `HEAD~1`) where CR wins on all three tasks.
- The reproducible harness in `eval/fastapi-crg/` becomes the release gate: every future release runs it and publishes the delta to `BENCHMARK_RESULTS.md`.

## v3.3 seed (intentionally deferred — new plan after v3.2 release)

Explicit: v3.3 scope is **not defined yet**. We will draft it fresh after v3.2 ships and after a second real-world eval round. No items are being pre-deferred here.
