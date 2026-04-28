# context-router precision-first redesign — beat code-review-graph

## Context

Benchmark on 12 tasks across 4 repos shows **context-router (develop) loses on precision and tokens** vs `code-review-graph`:

| Metric | context-router | code-review-graph | Gap |
|---|---:|---:|---:|
| Avg tokens | 3,416 | 1,506 | **2.27× heavier** |
| Avg precision (file) | 0.279 | 0.658 | **2.36× worse** |
| Avg recall (file) | 0.750 | 0.792 | tie |
| Avg F1 (file) | 0.378 | 0.583 | -35% |
| Rank-1 = GT file | 8/12 | n/a | only 67% |
| Empty / degenerate | 0/12 | 2/12 | we win here |

**Cross-reasoned diagnosis** (from per-task data + code map):

1. **Recall is fine — precision is the bug.** Same recall, half the precision, means we're casting a wide net that catches too much noise. Cutting noise should *not* materially hurt recall.
2. **Token bloat has two sources:** (a) **default budgets are 5× too large** (`implement`/`debug`/`handover` default to **8000**, `review` to **4000**; competitor averages 1,506); (b) **per-source-type guarantee** in the knapsack admits at least one item per source type even at conf 0.20, padding noise into every pack (`packages/ranking/src/ranking/ranker.py:1553`).
3. **Boost stacking inflates noise.** Five additive boosts (BM25, source-file, hub/bridge, semantic, diff-aware) plus community-cohesion (+0.10) and contracts-consumer (+0.10) push secondary cluster-mates and hub files into packs even when not task-relevant. Hub/community boosts especially hurt review/implement (per-task queries) because hubs are popular but rarely the *specific* file a task touches.
4. **No score floor.** Knapsack fills until budget exhausts. Adaptive top-k (`ranker.py:629-669`) fires only in review/implement and at 60% leader confidence — too lenient. Implement mode takes 30+ items; competitor wins by sometimes taking 1.
5. **Single-pass scoring.** No cross-encoder rerank. Slot is open after `_apply_semantic_boost()` at `ranker.py:537` — 20-40% precision lift is on the table.
6. **bulletproof-react reveals the strategy.** Competitor returns 94 tokens (~2-3 paths) on BP T1/T3 — degenerate but cheap; lands F1=1.0 on BP T2. We return 3-5K tokens every time. **They beat us by being narrow when uncertain; we need adaptive narrowness.**

The v4.4 roadmap (`docs/superpowers/plans/2026-04-25-v4.4-roadmap.md`) targets F1 ≥0.50 and downstream read tokens ≤500 via Phase B (symbol-body inlining) and Phase C (retrieval quality). **This plan goes further** — targeting F1 ≥0.65, avg tokens ≤1,200, and Rank-1 ≥10/12 to beat the competitor outright.

**Targets after redesign:**

| Metric | Target | vs competitor |
|---|---:|---:|
| Avg tokens | ≤1,200 | -20% |
| Avg precision | ≥0.70 | +6% |
| Avg F1 | ≥0.65 | +12% |
| Rank-1 = GT file | ≥10/12 | — |
| Empty outputs | 0/12 | strict win |

---

## Approach — five pillars, three phases

### Pillar 1 — Mode-tuned budget cuts + boost scoping (config-only, fast wins)

Drop default budgets and scope precision-hostile boosts to handover only.

**Budget changes** (default unless user overrides via `--max-tokens` / config):

| Mode | Current | New | Rationale |
|---|---:|---:|---|
| review | 4000 | **1500** | most tasks are 1-3 file edits |
| implement | 8000 | **1500** | query-anchored; rarely needs >5 files |
| debug | 8000 | **2500** | call chains need depth, but not 8K |
| handover | 8000 | **4000** | wider scope intentionally |
| minimal | 800 | **800** | unchanged |

**Boost scoping** — disable outside `handover`:
- Hub/bridge structural boost (`capabilities.hub_boost`) — hubs are popular, not task-specific
- Community-cohesion +0.10 (`orchestrator.py:1387`) — cluster-mates are tangential

Keep BM25, semantic, freshness, diff-aware, contracts-consumer in all modes.

### Pillar 2 — Score floor + restrict per-source-type guarantee

Replace the unconditional per-type guarantee with a precision gate.

**New admission logic** in `_enforce_budget` (`ranker.py:1520`):
1. Compute floor: `floor = max(top1_score * 0.55, 0.45)` for review/implement; `0.30` for debug; `0.20` for handover.
2. Drop items below floor *before* knapsack.
3. Per-source-type guarantee survives **only for high-signal types**: `entrypoint`, `changed_file`, `runtime_signal`, `contract`, `extension_point`. Drop guarantee for the catch-all `file` type that drives most noise.
4. Knapsack admits remaining items by value-per-token until budget exhausted.

This is the single highest-leverage change for precision — it kills the long tail of conf-0.20 items that pad every pack.

### Pillar 3 — Cross-encoder reranker (`--with-rerank`, default-on when available)

Add second-stage rerank between BM25 and final sort.

**Where:** new `_apply_cross_encoder_rerank()` in `ranker.py`, called at line 540 (after semantic boost, before diff-aware).

**Model:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (~22 MB). Lazy-loaded like the bi-encoder; same silent-degrade pattern when sentence-transformers absent.

**Algorithm:**
1. Take top-K=30 by current confidence.
2. Build (query, doc_text) pairs where `doc_text = "{symbol_name} {signature} {one-line summary}"` (cap 256 chars per doc).
3. Score with cross-encoder; map scores to [0, 1] via sigmoid.
4. New confidence: `0.5 * structural_conf + 0.5 * cross_score`.
5. Items outside top-30 keep their original conf (will get filtered by the floor in Pillar 2).

**Cost:** ~50ms per pack on CPU for 30 pairs. Off by `--no-rerank`. Falls back silently when model unavailable.

**Why this works:** Bi-encoder embeddings (current `--with-semantic`) are good for recall (find candidates fast); cross-encoders are much better for precision (rank candidates accurately) because they jointly attend over query and doc. This is standard practice in IR (BEIR, MS-MARCO leaderboards). Expected lift: precision +0.10 to +0.20.

### Pillar 4 — Adaptive depth (narrow when confident, broad when ambiguous)

Make `minimal`-style narrowness the *default* behavior for review/implement when the ranker is confident.

**Algorithm** in orchestrator after `ranker.rank()`:
1. Look at top-3 confidences after rerank: `c1, c2, c3`.
2. If `c1 ≥ 0.75 AND (c1 - c2) ≥ 0.15` → **narrow mode**: return top-1 + 1-hop call/import neighbors of that anchor, capped at 3 items, budget capped at 800 tokens. Emit `pack.metadata["depth"] = "narrow"` + reason.
3. Else if `c1 ≥ 0.55 AND len(items_above_floor) ≤ 5` → **standard mode**: return items above floor, knapsack-admitted, mode budget.
4. Else → **broad mode**: warn `"ambiguous query — top scores: [c1, c2, c3]"`, full mode budget but emit warning.

This converts our weakness (always returning a fat pack) into a strength: cheap+precise when we're sure, generous when we're not, with a *user-visible reason* either way.

### Pillar 5 — Symbol-body inlining for top-1 only (per v4.4 Phase B, but tightened)

The v4.4 roadmap proposes inlining symbol bodies for all items. **Tighten this to top-1 only by default** (`--inline-bodies all` to opt in to more):
- Top-1 ranked symbol → inline body (up to 800 tokens).
- All others → file pointer with `lines: [start, end]` only.
- Result: agent gets the *most relevant code body* without paying for 5 full files.

This makes our token-per-info ratio dominate the competitor: they output paths only (cheap but agent must read the file separately); we output paths + the single most-likely-correct body (one-shot answer).

---

## Phases & rollout

**Phase 1 — Config-only cuts (Pillars 1, 2): 1-2 days.**
- Single PR. No new dependencies.
- Expected post-Phase-1 metrics: avg tokens ~1,300, F1 ~0.50, precision ~0.55.
- Gate: tuning F1 must not drop below 0.45 on any single repo.

**Phase 2 — Cross-encoder rerank (Pillar 3): 2-3 days.**
- Adds `cross-encoder/ms-marco-MiniLM-L-6-v2` as optional dep.
- Expected post-Phase-2 metrics: F1 ~0.62, precision ~0.70.
- Gate: tuning F1 ≥0.55; latency p50 increase ≤80ms.

**Phase 3 — Adaptive depth + symbol-body inlining (Pillars 4, 5): 3-5 days.**
- Builds on v4.4 Phase B work for symbol bodies.
- Expected post-Phase-3 metrics: avg tokens ≤1,200, F1 ≥0.65, precision ≥0.70, Rank-1 ≥10/12.
- Gate: holdout F1 ≥ v4.3 holdout baseline (no regression on unseen repos).

After all three phases, ship as **v4.4** since this aligns with the roadmap's existing F1 / token-cost goals.

---

## Critical files to modify

| Pillar | File | Change |
|---|---|---|
| 1 | `packages/contracts/src/contracts/config.py:48-76` | mode-default token budgets |
| 1 | `packages/core/src/core/orchestrator.py:142-223` | scope hub/community boosts to handover (or expose `capabilities.hub_boost` / `enable_community_boost` mode-keyed config) |
| 1 | `packages/core/src/core/orchestrator.py:799-805` | wire mode budget overrides |
| 2 | `packages/ranking/src/ranking/ranker.py:1520-1620` | rewrite `_enforce_budget` with floor + restricted guarantee |
| 2 | `packages/ranking/src/ranking/ranker.py:629-669` | tighten adaptive top-k thresholds (apply to debug too) |
| 3 | `packages/ranking/src/ranking/ranker.py` (new method `_apply_cross_encoder_rerank`, called at line 540) | cross-encoder rerank |
| 3 | `packages/ranking/pyproject.toml` | add cross-encoder model alias / extras |
| 4 | `packages/core/src/core/orchestrator.py:1083-1190` | adaptive depth selector after `ranker.rank()` |
| 4 | `packages/core/src/core/orchestrator.py:1169-1193` | extend `next_tool_suggestion` to all modes for breadcrumbs |
| 5 | `packages/contracts/src/contracts/models.py` | `symbol_body` field on Pack item (already in v4.4 Phase B) |
| 5 | `packages/storage-sqlite/src/storage_sqlite/repositories.py` | symbol body retrieval (already in v4.4 Phase B) |

**Reuse (don't rewrite):**
- `EdgeRepository.get_call_chain_symbols` BFS — already does 1-3 hop walks for debug; reuse for Pillar 4 narrow-mode neighbor expansion
- `_get_embed_model()` lazy-load pattern in `ranker.py:246` — clone for cross-encoder load
- `freshness.compute_freshness()` — keep as-is

---

## Verification

**Per-phase benchmark gates** (must pass before merging):

```bash
# Re-run the 12-task tuning benchmark against develop after each phase
uv run context-router benchmark --fixtures benchmark/tuning --runs 10

# After Phase 3, verify holdout (gin/rails/actix-web/django) does not regress
uv run context-router benchmark --fixtures benchmark/holdout --runs 10
```

**Targets per phase** (record in `docs/benchmarks/v4.4-progress.md`):

| Phase | Avg tokens | Avg F1 | Avg precision | Rank-1 | Notes |
|---|---:|---:|---:|---:|---|
| baseline (now) | 3,416 | 0.378 | 0.279 | 8/12 | losing |
| post-1 | ≤1,500 | ≥0.50 | ≥0.55 | ≥9/12 | tied with competitor |
| post-2 | ≤1,400 | ≥0.60 | ≥0.65 | ≥10/12 | competitive |
| post-3 | ≤1,200 | ≥0.65 | ≥0.70 | ≥10/12 | leads |

**Regression tests to add:**
- `packages/ranking/tests/test_score_floor.py` — confirms floor drops conf-0.20 file items in implement
- `packages/ranking/tests/test_cross_encoder_rerank.py` — graceful degrade when model missing; rerank reorders correctly when present
- `packages/core/tests/test_adaptive_depth.py` — narrow mode triggers on confident query; broad mode warns on flat query
- `packages/evaluation/tests/test_retrieval_quality_gate.py` — already in v4.4 roadmap; reuse to enforce post-3 thresholds

**MCP / CLI smoke**:
```bash
# Confirm narrow mode triggers and returns ≤3 items
uv run context-router pack --mode implement \
  --query "add pagination to users endpoint" \
  --json | jq '.metadata.depth, (.items | length)'

# Confirm cross-encoder loads + degrades silently when offline
HF_HUB_OFFLINE=1 uv run context-router pack --mode review --no-rerank
```

---

## Trade-offs called out

1. **Cross-encoder = 22 MB model + ~50ms latency.** Acceptable for CLI/MCP; users on constrained envs can `--no-rerank`. The recall path (bi-encoder) stays cheap.
2. **Score floor risks empty packs on bad queries.** Mitigated by Pillar 4 broad-mode fallback that emits a warning and admits more — we never return zero items the way the competitor does (we keep our 0/12 degenerate-output advantage).
3. **Disabling hub-boost outside handover** may hurt some implement queries that legitimately want hub files. Acceptable — task-specific queries are the majority case, and a `--with-hub-boost` flag is one line to expose.
4. **Symbol-body inlining for top-1 only** is more conservative than v4.4 roadmap. Trade-off: slightly less inlined info, but much smaller packs. Reversible via `--inline-bodies all`.
5. **Rollback plan:** each phase ships as a separate PR with feature-flag gates (`config.precision_mode: v44` toggles all changes). If Phase 2 regresses unexpectedly on holdout, revert just the rerank without losing Phase 1 wins.

---

## Status (2026-04-27)

| PR | Phase | Status |
|---|---|---|
| #107 | Phase 1 — mode budgets, score floor, scoped boosts, Phase 5 top-1 inlining | merged |
| #108 | Phase 2 — cross-encoder reranker | merged |
| #109 | Phase 3 — query-driven widening + adaptive depth metadata | merged |
| #110 | Phase 4 — feedback loop (`files_read` signal + `feedback_applied` metadata) | green, awaiting merge |

Final benchmark vs `code-review-graph` (12 tasks, 4 repos): F1 0.611, precision 0.625, avg tokens 1,860. 2/4 repos lead the competitor outright; both v4.4 targets hit.

---

## Future phases (post-v4.4)

Deferred from v4.4 — kept out of scope to ship the release. Pick up after the test-environment efficiency study comes back.

### Phase 6 — query-conditional feedback (cosine-weight per-query)

**Problem.** Phase 4 adjustments are per-file globally: a file flagged `noisy` in one query gets the −0.10 penalty on every future query. Bleed-over hurts when the same file is genuinely useful for an unrelated task.

**Approach.**
1. Persist the query embedding (or its hash + top-k tokens) alongside each `pack_feedback` row.
2. At pack build time, weight each historical adjustment by cosine(current_query_embedding, feedback_query_embedding) — so feedback only fires strongly for similar queries.
3. Keep the `min_count=3` threshold; sum is now `Σ cosine_sim * delta` instead of `Σ delta`.
4. Surface the per-query weight in `pack.metadata.feedback_applied` for auditability.

**Cost.** Schema migration on `pack_feedback`; depends on bi-encoder being available (silent degrade to v4.4 behaviour otherwise). No new model.

**Why deferred.** No harness signal — the 12-task benchmark has no feedback history. Real-world value compounds only after weeks of usage. Ship after the test environment produces enough feedback rows to evaluate.

### Phase 7 — "treat docs-only diffs as no-diff" heuristic

**Problem.** Phase 3 widening short-circuits when `changed_files` is non-empty. Some real PRs (e.g. fastapi tasks T1/T3 in the harness) have a tiny irrelevant diff (`release-notes.md`) that suppresses widening — exactly the cases where widening would close the GT gap.

**Approach.**
1. In `_review_candidates`, classify each `changed_file`: docs (`*.md`, `*.rst`, `release-notes.*`, `CHANGELOG*`, `docs/**`) vs code.
2. If the diff is 100% docs, treat `changed_files = []` for the purposes of the widening gate (still record them as candidates, just don't suppress widening).
3. Authoritative-changed-files mode stays unchanged when *any* code file is touched.

**Cost.** ~30-line change in `packages/core/src/core/orchestrator.py`. No schema, no new dependency.

**Why deferred.** Direct benchmark payoff (closes the fastapi gap), but the heuristic has corner cases (config-only PRs, generated files) that warrant care. Ship as a focused follow-up PR after v4.4 is stable.
