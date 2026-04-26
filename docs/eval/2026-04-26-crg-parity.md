# CRG Parity Baseline - 2026-04-26

## Scope

Fixture: `eval/fastapi-crg/fixtures/tasks.yaml`
Repo: `/Users/mohankrishnaalavala/Documents/project_context/fastapi`
Output: `/Users/mohankrishnaalavala/Documents/project_context/fastapi/.eval_results_v44`

## Current Result

| Metric | context-router | code-review-graph |
|---|---:|---:|
| Avg tokens per task | 164 | 1,432 |
| Avg file precision | 0.333 | 0.833 |
| Avg file recall | 0.333 | 1.000 |
| Avg F1 | 0.333 | 0.889 |

## Required Gate

- context-router average F1 >= 0.80
- context-router average F1 / code-review-graph average F1 >= 1.00
- Token reduction remains a secondary metric; it cannot compensate for missing ground-truth files.

## Known Misses

- Task 1 misses `fastapi/security/oauth2.py` and selects docs/tests/scripts.
- Task 3 misses `fastapi/dependencies/utils.py` and selects tests.

## Diagnosis

Free-text debug/review-like tasks are being treated too much like test-failure
tasks. The ranker and candidate builder reward tiny tests/docs/scripts even when
the query asks for the source file to change.
