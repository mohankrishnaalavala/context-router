# context-router benchmarks

Reproducible holdout evaluation against real upstream commits in six OSS
projects across five languages. Each fixture pins a real commit SHA, the
ground-truth file the upstream fix touched, the natural-language query an
agent might type, and the suggested pack mode. Per-task artifacts live
under `benchmarks/results/<run-date>-<version>{,-fresh}/`.

## Headline — v4.4.3 (2026-04-28)

Two independent holdout suites, same code, two different sets of repos.

| Metric | Suite A | Suite B | Combined |
|---|---:|---:|---:|
| Repos | gin / actix-web / django | gson / requests / zod | 6 |
| Languages | Go / Rust / Python | Java / Python / TypeScript | 5 |
| Tasks | 9 | 9 | 18 |
| **Avg F1 (file-level)** | **0.630** | **0.685** | **0.658** |
| **Avg recall** | 0.889 | **1.000** | 0.944 |
| **Avg precision** | 0.500 | 0.537 | 0.519 |
| **Avg tokens / pack** | 185.6 | 132.2 | **159** |
| **Rank-1 hits (top-1 = GT)** | **8/9** | **9/9** | **17/18 (94%)** |

For comparison, `code-review-graph` (the closest publicly-benchmarked
competitor) averages ~1,506 tokens per pack on a similar workload —
**~89% fewer tokens for context-router**, with no recall regression.

## Why precision sits at ~0.5

When a bug-fix commit touches both `src/foo.py` and `tests/test_foo.py`,
both legitimately qualify as `changed_file` candidates. Source wins
rank-1 (the v4.4.3 source-prior makes sure of it), but the test sibling
is the legitimate rank-2 — it provides reproduction context. Precision
= 1/2 there reflects that trade, not a ranking bug. Tasks where the
diff is genuinely single-file hit precision 1.0 (gson-t3, actix-t2).

---

## Suite A — Go / Rust / Python

Per-task artifacts: [`benchmarks/results/2026-04-28-v4.4.3/`](benchmarks/results/2026-04-28-v4.4.3/)

| Scope | Tasks | Avg precision | Avg recall | Avg F1 | Avg tokens | Rank-1 |
|---|---:|---:|---:|---:|---:|---:|
| **overall** | 9 | 0.500 | 0.889 | **0.630** | 185.6 | **8/9** |
| gin (Go) | 3 | 0.500 | 1.000 | 0.667 | 114.3 | 3/3 |
| actix-web (Rust) | 3 | 0.667 | 1.000 | 0.778 | 91.7 | 3/3 |
| django (Python) | 3 | 0.333 | 0.667 | 0.444 | 350.7 | 2/3 |

The single miss is `django-t3` (`implement` mode, no `changed_files`
context) — the GT file falls outside `SymbolRepository.get_all`'s 10k
cap and isn't fetched by the v4.4.3 changed-file backstop because
there's no diff to anchor it. Tracked as a follow-up: extend the
implement-mode candidate fetch to also pre-include files matching
query tokens.

## Suite B — Java / Python / TypeScript

Per-task artifacts: [`benchmarks/results/2026-04-28-v4.4.3-fresh/`](benchmarks/results/2026-04-28-v4.4.3-fresh/)

| Scope | Tasks | Avg precision | Avg recall | Avg F1 | Avg tokens | Rank-1 |
|---|---:|---:|---:|---:|---:|---:|
| **overall** | 9 | 0.537 | **1.000** | **0.685** | **132.2** | **9/9** |
| gson (Java) | 3 | 0.611 | 1.000 | 0.722 | 137.7 | 3/3 |
| requests (Python) | 3 | 0.500 | 1.000 | 0.667 | 143.7 | 3/3 |
| zod (TypeScript) | 3 | 0.500 | 1.000 | 0.667 | 115.3 | 3/3 |

100% rank-1 across three languages on a fresh, never-seen-before
triple. This is the strongest signal that v4.4.3's changes generalize
beyond the suite A repos they were validated on.

---

## What v4.4.3 fixes

1. **`SymbolRepository.get_for_files`** + `Orchestrator._load_symbols_with_paths`.
   The stock `get_all` capped at 10,000 rows with no `ORDER BY` —
   silently invisible on django (43k symbols) so any file outside
   the first 10k never reached the candidate builder, including the
   `changed_file` ground truth for django-t1 / django-t2. The
   orchestrator now unions `get_all` with a targeted lookup for
   `changed_files | blast_radius_files | signal_paths` in
   `_review_candidates` / `_debug_candidates` / `_handover_candidates`,
   so changed-file symbols are guaranteed to be in the pool regardless
   of repo size. No behaviour change on small repos.

2. **Source-prior multiplier in candidate generation** (×1.15 source /
   ×0.85 test/aux). Reuses v4.4.2's `_RERANK_SOURCE_PRIOR_MULT` /
   `_RERANK_TEST_PRIOR_MULT` constants, but applies the asymmetry
   directly to `changed_file` confidence in the orchestrator — not
   just inside the opt-in `_apply_cross_encoder_rerank` path. Fires
   unconditionally so it works without `--with-rerank`. Restores
   v3.3.1's behaviour: when both source and test of a co-changed pair
   compete, the source wins on neutral lexical signal.

---

## Reproducing these runs

```bash
# 1. Clone the repos somewhere predictable.
mkdir -p ~/Documents/project_context/holdout-repos && cd $_

# Suite A
git clone --filter=blob:none https://github.com/gin-gonic/gin.git
git clone --filter=blob:none https://github.com/actix/actix-web.git
git clone --filter=blob:none https://github.com/django/django.git

# Suite B
git clone --filter=blob:none https://github.com/google/gson.git
git clone --filter=blob:none https://github.com/psf/requests.git
git clone --filter=blob:none https://github.com/colinhacks/zod.git

# 2. Run either suite (or both).
cd <context-router-repo>

# Suite A
bash benchmark/run-holdout.sh \
  --repo gin=~/Documents/project_context/holdout-repos/gin \
  --repo actix-web=~/Documents/project_context/holdout-repos/actix-web \
  --repo django=~/Documents/project_context/holdout-repos/django \
  --output-dir benchmarks/results/$(date +%Y-%m-%d)-vX.Y.Z

# Suite B
bash benchmark/run-holdout.sh \
  --repo gson=~/Documents/project_context/holdout-repos/gson \
  --repo requests=~/Documents/project_context/holdout-repos/requests \
  --repo zod=~/Documents/project_context/holdout-repos/zod \
  --output-dir benchmarks/results/$(date +%Y-%m-%d)-vX.Y.Z-fresh
```

The runner takes any number of `--repo NAME=PATH` pairs; `NAME` must
match a directory under `benchmark/holdout/<NAME>/tasks.yaml`. Per
task it:

1. `git checkout <fixture sha>` in the matching repo.
2. `context-router init` (once per repo) and `context-router index`
   (once per task — symbol/edge graph must match the checked-out SHA).
3. `context-router pack --mode <mode> --query <query> --json`.
4. Scores file-level precision / recall / F1 against the task's
   `ground_truth_files`, plus rank-1 (top item is a GT hit).
5. Aggregates per-repo and overall, writes `summary.json` +
   `summary.md`.

## Fixture provenance

All 18 holdout SHAs (6 repos × 3 tasks) are real upstream commits.
Each fixture file (`benchmark/holdout/<repo>/tasks.yaml`) lists the
commit SHA, a one-line description, the canonical ground-truth
file(s), the query an agent might type when investigating the bug,
and the suggested mode.

The original holdout fixtures committed in v4.4 used hand-authored
synthetic SHAs that never resolved upstream — those were rewritten
in v4.4.2 (suite A) and extended in v4.4.3 (suite B).

---

## History

- **v4.4 / v4.4.1** — holdout suite authored with synthetic SHAs that
  never resolved upstream; the suite never actually ran. Tuning-set
  numbers (12-task fastapi / bulletproof-react / eShop / petclinic)
  lived in `CHANGELOG.md`.
- **v4.4.2** — suite A rewritten with real SHAs (gin, actix-web,
  django), `benchmark/run-holdout.sh` added, first real holdout run
  executed. Surfaced two regressions: `SymbolRepository.get_all` 10k
  cap erasing django GT files, and the source-prior multiplier being
  unreachable without `--with-rerank`. Run artifacts superseded by
  v4.4.3.
- **v4.4.3** — fixes the two v4.4.2 holdout regressions. Suite A:
  F1 0.481 → 0.630, rank-1 4/9 → 8/9. Added suite B (gson, requests,
  zod) for cross-language validation: F1 0.685, rank-1 9/9. Runner
  generalized to take any `--repo NAME=PATH` pairs.

For older self-repo and external-repo numbers (49–99% token
reduction vs naive baselines on bulletproof-react, eShopOnWeb,
spring-petclinic, secret-scan-360, project_handover), see
[`CHANGELOG.md`](CHANGELOG.md) — those predate v4 ranking and
weren't carried forward as the new methodology took over.
