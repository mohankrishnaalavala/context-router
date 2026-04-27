# Multi-Repo CRG Validation - 2026-04-27

## Scope

Artifacts: `/tmp/context-router-multi-repo-crg-validation`

This run compares `context-router pack` and `code-review-graph detect-changes`
on the same real commit tasks across three local repos under
`/Users/mohankrishnaalavala/Documents/project_context`.

Each task ran in a temporary detached git worktree to avoid modifying the
source repo checkout. Ground truth is the source-code file set changed by the
fixture commit, filtered to the repo's primary language extensions.

## Tasks

| Repo | Commit | Query | Ground truth files |
|---|---|---|---:|
| `bulletproof-react` | `a55e984b980f0aeefef3500ddc070a516534f73d` | `Update auth.tsx` | 3 |
| `eShopOnWeb` | `267db4d87607cfde88ccccf9698425d499621c9d` | `Updating usings in order created handler` | 1 |
| `spring-petclinic` | `44d5f2100b1b829bc9fa10248ee841f5d1b28b2d` | `Remove jspecify annotations` | 16 |

## Results

| Repo | Task | Tool | Files | Tokens | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|---:|
| `bulletproof-react` | `bulletproof-auth-tsx` | context-router | 3 | 141 | 1.000 | 1.000 | 1.000 |
| `bulletproof-react` | `bulletproof-auth-tsx` | code-review-graph | 0 | 87 | 0.000 | 0.000 | 0.000 |
| `eShopOnWeb` | `eshop-order-handler-usings` | context-router | 3 | 162 | 0.333 | 1.000 | 0.500 |
| `eShopOnWeb` | `eshop-order-handler-usings` | code-review-graph | 0 | 87 | 0.000 | 0.000 | 0.000 |
| `spring-petclinic` | `petclinic-jspecify-removal` | context-router | 29 | 1,640 | 0.379 | 0.688 | 0.489 |
| `spring-petclinic` | `petclinic-jspecify-removal` | code-review-graph | 11 | 10,962 | 1.000 | 0.688 | 0.815 |

## Aggregate

| Metric | context-router | code-review-graph |
|---|---:|---:|
| Avg tokens | 648 | 3,712 |
| Avg precision | 0.571 | 0.333 |
| Avg recall | 0.896 | 0.229 |
| Avg F1 | 0.663 | 0.272 |

## Interpretation

On this three-task sample, context-router beats code-review-graph on aggregate
F1 and token count. The result is directionally useful, not definitive:

- context-router is clearly better on the TypeScript task and catches the C#
  changed file that code-review-graph did not surface through `detect-changes`.
- code-review-graph is stronger on the Java task: same recall as
  context-router, much better precision.
- The next reliability target is Java source-discovery precision. The current
  source-discovery path protects recall, but can keep too many same-package
  neighbors on broad mechanical commits.
