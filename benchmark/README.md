# context-router Benchmark Fixtures

## Structure

- `benchmark/tuning/` — 12-task tuning set (fastapi, bulletproof-react, eShopOnWeb, spring-petclinic)
  - Used to tune and validate ranker changes.
  - Driven by `eval/fastapi-crg/run.sh` (fastapi) and judge-agent reports for the other three.

- `benchmark/holdout/` — 9-task holdout set (gin, actix-web, django)
  - 3 tasks per repo, real upstream commits, single-source-file ground truth.
  - **NEVER tune the ranker against these tasks.**
  - Added in v4.4; rewritten with real SHAs in v4.4.2.
  - Gate: each release must not regress holdout F1 vs prior release.
  - Rails was dropped from the holdout set (no Ruby coverage in the v4.4.2
    benchmark window — track separately if Ruby support tightens up).

## Running

```bash
# Holdout set — runs the 9 tasks across gin, actix-web, django and writes
# per-task JSON + an aggregate Markdown report.
bash benchmark/run-holdout.sh \
  --gin-root      ~/Documents/project_context/holdout-repos/gin \
  --actix-root    ~/Documents/project_context/holdout-repos/actix-web \
  --django-root   ~/Documents/project_context/holdout-repos/django \
  --output-dir    docs/benchmarks/holdout-runs/$(date +%Y-%m-%d)
```

The runner checks out each fixture SHA, re-indexes context-router, runs
`context-router pack` with the task's mode + query, scores file-level
precision/recall/F1 against `ground_truth_files`, and aggregates per-repo
and overall.

## Repos to clone for running benchmarks

```bash
# Tuning set repos
git clone https://github.com/tiangolo/fastapi.git
git clone https://github.com/alan2207/bulletproof-react.git
git clone https://github.com/dotnet-architecture/eShopOnWeb.git
git clone https://github.com/spring-projects/spring-petclinic.git

# Holdout set repos
git clone https://github.com/gin-gonic/gin.git
git clone https://github.com/actix/actix-web.git
git clone https://github.com/django/django.git
```
