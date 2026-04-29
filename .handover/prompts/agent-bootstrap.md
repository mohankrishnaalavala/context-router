# Agent bootstrap — context-router

**Single source of truth for any AI coding agent (Claude, Cursor, Copilot, Gemini, Windsurf, Codex, etc.) working on this repo.** All agent rule files (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.windsurfrules`) reference this document.

This repo IS context-router. We dogfood — agents working on context-router use context-router itself for retrieval. Do not reach for other knowledge-graph tools; this repo's MCP stack is `context-router` plus optional `sequential-thinking`.

---

## Hard rules — every session

### 1. MCP setup (one-time, already configured)

The repo ships `.mcp.json` pointing at `context-router mcp` over stdio. If your agent supports MCP, the tools below are already available. Otherwise call the CLI directly (`context-router pack ...`).

### 2. Start of session — before opening any file

```
search_memory(query="<topic of current task>")
get_context_pack(mode="handover")
```

`search_memory` returns the last session's observations — what was tried, what worked, what didn't. `get_context_pack(mode="handover")` returns the most relevant files ranked by recency. Read both before opening anything else. This typically gives full context in <500 tokens; manually opening 5 files burns 5,000.

For a fresh session resuming prior work, also read `.handover/prompts/continue.md`.

### 3. While working — keep the index live

In a separate terminal, run:

```bash
context-router watch
```

This incrementally re-indexes on file save so subsequent `pack` / `search_memory` calls see your current state, not what was indexed at session start. Without it, you'll get stale results after 10 minutes of edits.

### 4. End of session — required before clearing chat

```python
save_observation(
    summary="<60+ char summary of what was done and why>",
    task_type="implement",   # or debug / review / handover
    files_touched=["packages/foo/src/foo/bar.py", "..."],
    fix_summary="<optional: what was broken and how it was fixed>",
)
```

Then commit the markdown file `save_observation` writes:

```bash
git add .context-router/memory/observations/
git commit -m "chore(memory): observation from <task>"
```

This is **not optional**. The repo's compounding-memory thesis only works if every session leaves an observation behind. Skipping it once is fine; making it a habit drains the value of the tool.

### 5. Architectural decisions — record them

Any non-trivial design call (library pick, pattern choice, schema change, behavior change in a public contract) gets:

```python
save_decision(
    title="<short title>",
    rationale="<why this over alternatives>",
    alternatives=["<rejected option 1>", "..."],
    impact_files=["packages/foo/...", "..."],
)
```

ADRs land under `.context-router/decisions/` and surface in future `get_decisions(query=...)` calls.

---

## Workflow shortcuts

| Task | First call |
|---|---|
| Implementing something new | `get_context_pack(mode="implement", query="...")` |
| Reviewing a diff | `get_context_pack(mode="review")` (auto-detects working diff) |
| Debugging a failure | `get_debug_pack(query="...", error_file="pytest.xml")` |
| Onboarding to a feature area | `get_context_pack(mode="handover", query="...")` |
| Quick triage | `get_minimal_context(query="...")` (≤5 items, ≤800 tokens) |
| Tracing call chain | `get_call_chain(symbol="...", depth=2)` |
| Suggesting next files | `suggest_next_files(seed_files=[...])` |

Fall back to `Grep`, `Glob`, `Read` **only** when context-router doesn't cover what you need (e.g., reading a specific file you already know the path of). Reaching for grep before MCP is a code smell on this repo — log a follow-up ("MCP didn't surface X") so we can improve the tool.

---

## What NOT to do

- ❌ **Never recommend or wire in `code-review-graph` for this repo.** It's a separate tool with overlapping scope. We dogfood our own stack. Earlier versions of this repo had `code-review-graph` references in agent rule files; they were removed in v4.4.4.
- ❌ Don't open files via `Read` before calling `search_memory` + `get_context_pack`. Past sessions almost always have relevant observations.
- ❌ Don't skip `save_observation` "because the change was small." Small changes accumulate the most valuable institutional knowledge (gotchas, weird invariants).
- ❌ Don't bypass `context-router watch` and rely on the stale index. If you don't want a long-running process, run `context-router index` after every batch of edits.

---

## Repo conventions (CLAUDE.md / AGENTS.md call these out further)

- `git pull origin main` into `develop` before starting work. Open PRs from `develop → main`. No direct commits to `main`.
- One conventional-commit per logical concern.
- All tests must stay green: `uv run pytest --tb=short -q` (476+ tests).
- Lint: `uv run ruff check .`
- Outcome-based DoD per `docs/release/dod-template.md` before any code change touches a release outcome.
- No silent failures: any flag/mode/tool that has no effect must emit a stderr warning.

---

## Pre-PR checklist

1. `uv run pytest` green
2. `uv run ruff check .` clean
3. `save_observation` committed with the work
4. CHANGELOG entry under the right version section
5. PR body includes a `/ship-check` verdict block
