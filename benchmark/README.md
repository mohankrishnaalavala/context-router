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
