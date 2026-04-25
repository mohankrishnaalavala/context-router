# context-router Benchmark Fixtures

## Structure

- `benchmark/tuning/` — 12-task tuning set (fastapi, bulletproof-react, eShopOnWeb, spring-petclinic)
  - Used to tune and validate ranker changes
  - v4.3 baseline: avg F1=0.394, avg tokens=1,577

- `benchmark/holdout/` — 12-task holdout set (gin, rails, actix-web, django)
  - **NEVER tune the ranker against these tasks**
  - Added in v4.4 to detect overfitting
  - Gate: each release must not regress holdout F1 vs prior release

## Running

```bash
# Tuning set
uv run context-router benchmark --fixtures benchmark/tuning

# Holdout set (regression gate)
uv run context-router benchmark --fixtures benchmark/holdout
```

## Repos to clone for running benchmarks

```bash
# Tuning set repos
git clone https://github.com/tiangolo/fastapi.git
git clone https://github.com/alan2207/bulletproof-react.git
git clone https://github.com/dotnet-architecture/eShopOnWeb.git
git clone https://github.com/spring-projects/spring-petclinic.git

# Holdout set repos
git clone https://github.com/gin-gonic/gin.git
git clone https://github.com/rails/rails.git
git clone https://github.com/actix/actix-web.git
git clone https://github.com/django/django.git
```
