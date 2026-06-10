---
id: 2026-06-10-v45-task-8-phase-c-re-judge-post-hygie
type: observation
task: implement
files_touched:
  - packages/ranking/tests/test_source_file_boost.py
  - packages/ranking/src/ranking/ranker.py
  - packages/ranking/tests/test_ranker.py
  - docs/eval/2026-06-10-v4.5-phase-c-rebaseline.md
created_at: 2026-06-10T13:10:41.869267+00:00
author: context-router
---

v4.5 Task 8 Phase C re-judge: post-hygiene tuning F1 re-baselined at 0.613 (vs v4.3's 0.394, v3.3.0's 0.577) on the 12-task fastapi/bulletproof-react/eShopOnWeb/spring-petclinic set. C1 source-file boost + C3 ABS_FLOOR=0.40 were already shipped (746e84d, 14d6462) and ablate neutral — kept; C1's missing roadmap tests added. C2 semantic default-on measured at F1 0.537 (-0.076, precision and eShopOnWeb T3 recall losses) — ranker use_embeddings default reverted to False, semantic stays opt-in via --with-semantic. Full report: docs/eval/2026-06-10-v4.5-phase-c-rebaseline.md

Kept C1/C3 as shipped (neutral post-hygiene), reverted C2 ranker default to opt-in based on measured F1 regression; eval driver used fresh per-SHA index so the v4.5 hygiene pruning applied to all fixture repos.
