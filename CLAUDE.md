# context-router

> Routes AI coding agents to minimum useful context — reducing token waste across review, debug, implement, and handover tasks. Local-first, no API key required, benchmarkable.

## Quick orientation

| You want to know… | Read this |
|---|---|
| What this is | [.handover/context/overview.md](.handover/context/overview.md) |
| Architecture & packages | [.handover/context/architecture.md](.handover/context/architecture.md) |
| Decisions (ADRs) | [.handover/context/decisions.md](.handover/context/decisions.md) |
| Milestones & release status | [.handover/work/milestones.md](.handover/work/milestones.md) |
| Current spec | [.handover/work/spec.md](.handover/work/spec.md) |
| Open tasks | [.handover/work/tasks.md](.handover/work/tasks.md) |
| Coding standards | [.handover/standards/coding-standards.md](.handover/standards/coding-standards.md) |
| Constraints & non-goals | [.handover/context/constraints.md](.handover/context/constraints.md) |
| Open risks | [.handover/context/risks.md](.handover/context/risks.md) |

**Starting a new session?** Run `get_context_pack(mode="handover")` first, then open the matching prompt in `.handover/prompts/`.

---

## Development flow

Every change, every time — no exceptions:

1. `git pull origin main` into `develop` before starting
2. Implement; all tests must stay green (`uv run pytest`)
3. Commit with a conventional-commit message (one logical concern per commit)
4. Push `develop` → open PR to `main` → watch CI → diagnose and fix before handing back

**Requires approval before executing:** merging PRs, releases, tags, force-push, any action that notifies other humans.

---

## Quality gate — three rules that block every merge

1. **Outcome-based DoD before any code.** Copy `docs/release/dod-template.md`, fill all four fields (`outcome`, `threshold`, `negative_case`, `verify`), and add an entry to `docs/release/v4-outcomes.yaml`. A spec without a filled DoD is not mergeable.

2. **No silent failures.** Any flag, mode, or tool that has no effect in a given context MUST emit a warning to stderr naming the reason. Silent no-ops are rejected in review regardless of test coverage.

3. **Ship-check before "done".** Run `/ship-check` and paste the verdict block into the PR body. No verdict = no merge.

---

## MCP tools — call before opening any file

Use both tools in sequence: context-router scopes the task, code-review-graph traces structure.

**context-router** (start here)

| Call | When |
|---|---|
| `get_context_pack(mode=..., query=...)` | Starting any implement / review / handover task |
| `get_debug_pack(query=..., error_file=...)` | Debugging a failure |
| `search_memory(query=...)` | Finding past observations on a topic |
| `get_decisions(query=...)` | Looking up architectural decisions |
| `save_observation(...)` | After every completed task — required, not optional |

**code-review-graph** (trace structure)

| Call | When |
|---|---|
| `semantic_search_nodes` / `query_graph` | Exploring code — use instead of grep/glob |
| `get_impact_radius` | Blast radius before modifying a file |
| `detect_changes` + `get_review_context` | Code review without reading full files |

---

## Production standards

All code merged to `main` must meet this bar:

- **Outcome-verified.** Smoke tests check user-visible results; unit tests check internals. Both must pass — a green unit suite does not substitute for a failing smoke test.
- **Explicit contracts.** Every `ContextItem` carries `reason`, `confidence`, and `est_tokens`. Every pack carries `budget.total_tokens`, `budget.memory_tokens`, `budget.memory_ratio`. Never omit these fields.
- **No silent degradation.** Fallback behavior (missing config, unavailable git, empty memory) must warn to stderr with a named reason and still return a valid, partial result.
- **Stable public surface.** CLI flags and MCP tool signatures are stable across patch versions. Breaking changes require a semver major bump and a migration note in CHANGELOG.
- **Minimal shipped surface.** No speculative features, no unused parameters, no commented-out code in merged PRs. Ship the smallest mergeable version.
- **Observability first.** Budget usage, memory hits, ranking decisions, and plugin warnings must always be surfaced — never hidden behind silent defaults.
