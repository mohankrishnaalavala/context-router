---
id: 2026-04-26-v44-implementation-complete-6-language
type: observation
task: implement
files_touched:
  - packages/contracts/src/contracts/models.py
  - packages/storage-sqlite/src/storage_sqlite/repositories.py
  - packages/core/src/core/orchestrator.py
  - packages/ranking/src/ranking/ranker.py
  - packages/evaluation/src/evaluation/downstream.py
  - packages/evaluation/src/evaluation/report.py
  - packages/language-go/
  - packages/language-rust/
  - packages/language-ruby/
  - packages/language-php/
  - packages/language-sql/
  - packages/language-typescript/
  - docs/eval/v4.3-baseline.json
  - docs/release/v4-outcomes.yaml
  - benchmark/holdout/
created_at: 2026-04-26T00:52:17.545323+00:00
author: context-router
---

v4.4 implementation complete: 6 language analyzers (Go/Rust/Ruby/PHP/SQL/JS), symbol body enrichment (B1-B3), source-file boost + semantic re-rank defaults (C1-C2), downstream read metric (A1), holdout fixtures (A2)

Two test failures fixed post-C2: oauth2 test assertion updated (test file correctly cut by Rule 1, not a bug); file-dedup test raised PetController confidence to 0.6 and switched to debug mode to isolate dedup from adaptive top-k.
