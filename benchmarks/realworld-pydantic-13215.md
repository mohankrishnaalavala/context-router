# v4.5.0 pre-release real-world validation — pydantic issue #13215

**Date:** 2026-06-10
**Build under test:** context-router 4.5.0 (main @ 5675b4e, post PR #120 merge)
**Target repo:** pydantic/pydantic @ `a20c0ee` — the parent of merge
`5f89299` (PR #13243). Pydantic is NOT in the holdout benchmark set, so
this is a fresh, unseen workload.
**Task:** real closed issue
[#13215](https://github.com/pydantic/pydantic/issues/13215) —
"`__slots__` is not propagated to generic parameterizations, silently
re-adding `__weakref__`".
**Ground truth (from the maintainers' fix):** the only source file
changed by PR #13243 is `pydantic/_internal/_generics.py`
(function `create_generic_submodel`).

## Protocol

1. Clone pydantic, check out the pre-fix commit (the fix must not exist
   in the tree).
2. Index with the release-candidate build; run every user-facing
   feature against the real repo.
3. Query packs with (a) issue title only — hard retrieval case, and
   (b) full issue body — what an agent actually receives.
4. Record rank of the ground-truth file, pack tokens, and end-to-end
   tokens vs a naive-agent baseline.

## Headline result

| Metric | Value |
|---|---:|
| Pack tokens (full issue body, implement mode) | 4,811 |
| Ground-truth file rank | **3 / 37** |
| Ground-truth *function* identified | **yes — `create_generic_submodel`, lines 105–149** |
| Downstream read (symbol_lines span, 45 lines) | ~450 |
| **End-to-end tokens (context-router)** | **~5,260** |
| Naive-agent baseline (grep + read the 5 plausible files in full) | 94,772 |
| **End-to-end reduction** | **~94.5%** |

The naive baseline is conservative: it assumes the agent picks exactly
the right 5 files (`_generics.py`, `_model_construction.py`, `main.py`,
`_generate_schema.py`, `tests/test_generics.py`) and reads nothing
else. Real agents typically read more.

CLI and MCP server return identical results (rank 3, 4,811 tokens) for
the same query.

**Title-only query (hard case):** ground truth NOT in top 20. Root
cause is instructive: the pre-fix `_generics.py` contains neither
`__slots__` nor `__weakref__` anywhere — the absence of that handling
*is* the bug — so keyword retrieval has nothing to anchor on. The pack
still surfaced the right neighborhood (`_model_construction.py`,
`_generate_schema.py`). This is the case semantic re-rank
(`--with-semantic`, opt-in) is designed for; without the `[semantic]`
extra installed the flag degrades loudly and correctly (see below).

## Feature sweep (all on the real repo)

| Feature | Result |
|---|---|
| `index` (cold) | PASS — 561 files, 15,623 symbols, 24,718 edges in **7.85s** |
| `index` (re-run, stability) | PASS — symbol/edge counts stable across runs 3–4; an appended function is picked up and survives prune |
| `doctor` | PASS — all analyzers load; **index-pollution: 0% vendored** |
| `graph` | PASS — 500 real pydantic nodes (`BaseModel`, `ConfigDict`, …), loud truncation WARN with `--max-nodes` remedy |
| `pack --mode implement` (CLI) | PASS — GT rank 3 with exact fix function + line span |
| `pack --with-semantic` w/o extra | PASS (honesty contract) — warns `semantic model is unavailable; semantic re-ranking skipped`, still returns a valid pack |
| `embed` w/o extra | PASS (honesty contract) — clean error naming the install command |
| `explain last-pack` | PASS — human-readable rationale with line ranges |
| symbol-body packs | PASS — top item gets inlined body; rest get `symbol_lines` pointers (precision-first, as designed) |
| MCP server | PASS — initialize, 17 tools listed, `get_context_pack` / `save_observation` / `search_memory` / `list_memory` all verified over stdio JSON-RPC |
| No-silent-failure audit | PASS — every degradation observed (get_all cap, graph truncation, dropped external placeholders, missing semantic model, fallback reasons) emitted a named stderr warning |

## Findings filed for v4.6 (none block the release; none are v4.5 regressions)

1. **`get_all` 10k-row cap hits internal callers on >10k-symbol repos.**
   Pydantic has 15,623 symbols; the cap WARN fires during `index` and
   `pack`. The warning (new in v4.5) is doing its job — but internal
   pipeline callers should page instead of consuming a partial slice.
2. **Duplicate edges from same-named local classes.** Pydantic tests
   define `class Model(BaseModel)` hundreds of times per file; symbols
   collapse to one row but the writer emits one edge per occurrence
   (worst case: 161 identical `extends → BaseModel` rows). Inflates
   degree-based ranking toward test files. Fix: `INSERT OR IGNORE` /
   unique constraint + qualify nested symbol names.
3. **Edge-count reporting inconsistency.** First index reports 24,718
   edges, subsequent runs 27,915, while the DB holds 24,253 rows.
   Stable (no unbounded growth), but the reported number and the
   stored number should agree.
4. **Pack JSON shape:** CLI emits both `items` and `selected_items`
   (duplicate payload); MCP emits only `selected_items`. Pick one and
   document it.

## v4.6 re-validation (2026-06-11, develop post-Phase A)

Re-indexed the same clone (`a20c0ee`) with the Phase A build (edge dedup
+ UNIQUE constraint, scope-qualified symbol identity, honest counts,
iter_all paging) and re-ran the full-issue-body pack.

**Findings 1–3 above are confirmed fixed:**

- **No `get_all` cap WARN** during `index` on the 15,623-symbol repo
  (finding 1). The only WARN was the intentional, loud
  `0017_symbol_qualified_name` pack-cache discard.
- **0% duplicate edge rows** (was 37.56% redundant). The 161 identical
  `Model → extends → BaseModel` rows from `tests/test_types.py` are now
  161 *distinct* edges from 161 scope-qualified `Model` symbols
  (finding 2).
- **Reported == stored:** `Indexed 561 files — 15,623 symbols, 17,425
  edges`; DB holds exactly 17,425 edge rows and 15,623 non-`<external>`
  symbols (finding 3).

**Pack result (same protocol: full issue body, implement mode):**

| Metric | v4.5.0 | v4.6 (post-Phase A) |
|---|---:|---:|
| Items | 37 | 37 |
| Pack tokens | 4,811 | 4,803 |
| GT file rank (`_internal/_generics.py`) | **3** | **6** |
| GT function pointer | `create_generic_submodel` 105–149 | `create_generic_submodel` 105–149 (unchanged, exact) |

**The `rank <= 3` ship-gate claim does NOT hold post-fix: rank is 6/37**
(stable across repeated runs). The function-level pointer is still
exact and the file is still in the top 16% of the pack. Ranks 4–5 are
`get_name` symbols from `pydantic-core/src/**/*.rs` at confidence
0.821 vs the ground truth's 0.819 — a 0.002 gap. Root cause verified:
NOT degree inflation (the `.rs` `get_name` symbols have zero inbound
edges) and NOT vendor pollution (`pydantic-core/` is git-tracked in
the pydantic repo at this commit — it's a monorepo, so the Rust
sources are legitimately own-code). The Rust items rank on
content/contract relevance despite the query being a plainly Python
issue (a `.py` traceback). The honest v4.5 comparison: rank 3 sat
partly on duplicate-edge degree inflation that A1/A2 removed.

**Adjudication (owner-approved 2026-06-11, v4.6.0 release):**
re-baseline the gate to "GT file in top 6 of 37 with exact function
pointer" — met (rank 6, `create_generic_submodel` lines 105–149 exact,
4,803 tokens). **Cross-language query affinity** (down-weight files
whose language cannot match a language-explicit query) is filed for
v4.7 alongside the resolution-quality work — measured against the full
holdout eval, not this single task, to avoid overfitting the benchmark.

Secondary note: a debug-mode pack with the same query (no error file)
returns 7 items / 1,304 tokens without the GT file — debug mode keys on
runtime signals that this query lacks; it was not the gated metric in
v4.5 and is recorded here only for completeness.

## Verdict

**PASS — safe to tag v4.5.0.** On a real, unseen repo and a real issue,
the release candidate routed an agent to the exact fix function for
~5.3k tokens end-to-end (~94.5% below a conservative naive baseline),
with every degradation loud and every feature exercised.
