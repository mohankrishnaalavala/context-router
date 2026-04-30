# context-router Benchmark Fixtures

## Structure

- `benchmark/tuning/` — 12-task tuning set (fastapi, bulletproof-react, eShopOnWeb, spring-petclinic)
  - Used to tune and validate ranker changes.
  - Driven by `eval/fastapi-crg/run.sh` (fastapi) and judge-agent reports for the other three.

- `benchmark/holdout/` — holdout set
  - Suite A (v4.4.2): gin, actix-web, django — 9 tasks
  - Suite B (v4.4.3): gson, requests, zod — 9 tasks
  - Suite C (v4.4.4): kubernetes — 3 tasks, polyglot, 197K symbols
  - Real upstream commits, single-source-file ground truth.
  - **NEVER tune the ranker against these tasks.**
  - Gate: each release must not regress holdout F1 vs prior release.
  - Rails was dropped from the holdout set (no Ruby coverage in the v4.4.2
    benchmark window — track separately if Ruby support tightens up).

## Running

```bash
# Suite A — runs 9 tasks across gin, actix-web, django and writes
# per-task JSON + an aggregate Markdown report.
bash benchmark/run-holdout.sh \
  --repo gin=~/Documents/project_context/holdout-repos/gin \
  --repo actix-web=~/Documents/project_context/holdout-repos/actix-web \
  --repo django=~/Documents/project_context/holdout-repos/django \
  --output-dir docs/benchmarks/holdout-runs/$(date +%Y-%m-%d)
```

The runner checks out each fixture SHA, re-indexes context-router, runs
`context-router pack` with the task's mode + query, scores file-level
precision/recall/F1 against `ground_truth_files`, and aggregates per-repo
and overall.

### Anchor configurations (v4.4.4)

To distinguish "the input contained the answer" from "retrieval actually
worked," every kubernetes task is run under three anchors. Other suites
accept the flag too — defaults to `fix-sha` for backward compat.

```bash
# Easy — checkout the fix SHA, run task as-is. For review tasks the diff
# already names the GT files at confidence 0.95, so this is a confidence
# check, not a retrieval benchmark.
bash benchmark/run-holdout.sh --repo kubernetes=… --anchor fix-sha

# Fair — checkout the parent (fix^), force review mode, pass --pre-fix
# <fix-sha> so the pack ranks from the diff. This is the headline number.
bash benchmark/run-holdout.sh --repo kubernetes=… --anchor parent-sha-with-diff

# Hard — checkout the parent (fix^), force implement mode, query only.
# Stresses candidate retrieval on >10K-symbol repos with no diff anchor.
bash benchmark/run-holdout.sh --repo kubernetes=… --anchor query-only
```

The anchor lands in every per-task `score_*.json`, in `summary.json`, and
at the top of `summary.md` so reproducer numbers can verify the config.

### Workload-matched competitor comparison (v4.4.4 Phase 3)

`benchmark/run-comparison.sh` runs the same fair-config workload
(`parent-sha-with-diff`) against `code-review-graph` so the published
side-by-side numbers come from identical SHAs and identical diffs as input.

```bash
# 1. Run context-router under parent-sha-with-diff first (produces score_*.json).
bash benchmark/run-holdout.sh \
  --repo kubernetes=$HOME/Documents/project_context/holdout-repos/kubernetes \
  --anchor parent-sha-with-diff \
  --output-dir docs/benchmarks/holdout-runs/$(date +%Y-%m-%d)-k8s-parent-sha-with-diff

# 2. Install code-review-graph in its own venv.
uv venv .venv-crg --python 3.12
.venv-crg/bin/python -m pip install code-review-graph
.venv-crg/bin/code-review-graph --help

# 3. Run the comparison — checks out each fix SHA, runs CRG `build` then
#    `detect-changes --base <sha>^`, captures predicted files / tokens /
#    runtime / exit status. Mirrors context-router's matching score_*.json
#    so a single summary contains both tools.
bash benchmark/run-comparison.sh \
  --repo kubernetes=$HOME/Documents/project_context/holdout-repos/kubernetes \
  --cr-output-dir docs/benchmarks/holdout-runs/$(date +%Y-%m-%d)-k8s-parent-sha-with-diff \
  --crg-bin "$PWD/.venv-crg/bin/code-review-graph" \
  --output-dir benchmarks/results/$(date +%Y-%m-%d)-comparison
```

If `code-review-graph` errors on a task, the failure mode (exit status,
stderr tail) is captured in the per-task `comparison_*.json` and surfaced
in the summary — tasks are never silently skipped.

## Repos to clone for running benchmarks

```bash
# Tuning set repos
git clone https://github.com/tiangolo/fastapi.git
git clone https://github.com/alan2207/bulletproof-react.git
git clone https://github.com/dotnet-architecture/eShopOnWeb.git
git clone https://github.com/spring-projects/spring-petclinic.git

# Holdout set repos — Suite A
git clone https://github.com/gin-gonic/gin.git
git clone https://github.com/actix/actix-web.git
git clone https://github.com/django/django.git

# Holdout set repos — Suite B
git clone https://github.com/google/gson.git
git clone https://github.com/psf/requests.git
git clone https://github.com/colinhacks/zod.git

# Holdout set repos — Suite C (large; ~3 GB)
git clone https://github.com/kubernetes/kubernetes.git
```
