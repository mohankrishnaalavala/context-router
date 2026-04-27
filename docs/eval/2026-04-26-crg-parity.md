# CRG Parity Baseline - 2026-04-26

## Scope

Fixture: `eval/fastapi-crg/fixtures/tasks.yaml`
Repo: `/Users/mohankrishnaalavala/Documents/project_context/fastapi`
Output: `/Users/mohankrishnaalavala/Documents/project_context/fastapi/.eval_results_v44`

## Historical v4.4 Artifact Baseline

| Metric | context-router | code-review-graph |
|---|---:|---:|
| Avg tokens per task | 164 | 1,432 |
| Avg file precision | 0.333 | 0.833 |
| Avg file recall | 0.333 | 1.000 |
| Avg F1 | 0.333 | 0.889 |

## Live Gate Reproduction Before Fixes

Source: `/tmp/context-router-crg-parity-before/summary.md`

| Metric | context-router | code-review-graph |
|---|---:|---:|
| Avg tokens per task | 8,048 | 1,507 |
| Avg file precision | 0.007 | 0.833 |
| Avg file recall | 1.000 | 1.000 |
| Avg F1 | 0.014 | 0.889 |
| Avg token reduction | 98.8% | 99.8% |

The live gate includes the gold files, but precision is terrible because
context-router returns roughly 140 files per task.

## Live Gate After CRG-Parity Fixes

Source: `/tmp/context-router-crg-parity-after/summary.md`

| Metric | context-router | code-review-graph |
|---|---:|---:|
| Avg tokens per task | 84 | 1,432 |
| Avg file precision | 0.833 | 0.833 |
| Avg file recall | 1.000 | 1.000 |
| Avg F1 | 0.889 | 0.889 |
| Avg token reduction | 100.0% | 99.8% |

Per-task result:

- Task 1 selects `fastapi/security/oauth2.py`.
- Task 2 selects `scripts/people.py`.
- Task 3 selects `fastapi/dependencies/utils.py` and
  `tests/test_forms_single_model.py`, matching code-review-graph's file set.

## Required Gate

- context-router average F1 >= 0.80
- context-router average F1 / code-review-graph average F1 >= 1.00
- Token reduction remains a secondary metric; it cannot compensate for missing ground-truth files.

## Historical v4.4 Artifact Known Misses

- Task 1 misses `fastapi/security/oauth2.py` and selects docs/tests/scripts.
- Task 3 misses `fastapi/dependencies/utils.py` and selects tests.

## Diagnosis

Free-text debug/review-like tasks are being treated too much like test-failure
tasks. The ranker and candidate builder reward tiny tests/docs/scripts even when
the query asks for the source file to change.
