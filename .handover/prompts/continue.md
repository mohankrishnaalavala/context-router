# Resume Session — context-router

Use this prompt when resuming work after a break (hours, days, or weeks).

---

## Step 1 — Recover context via context-router MCP (do this before reading any file)

```
get_context_pack(mode="handover")
```

This surfaces the most relevant files ranked by recency and task relevance. Read the result before doing anything else.

```
search_memory(query="<topic of current work, e.g. v4.3 staleness>")
```

This returns the last session's observations. The summaries tell you exactly what state was left in.

## Step 2 — Check what's open

Read `.handover/work/tasks.md` — the v4.3 task list with open checkboxes is your next action.

Run `git log --oneline -10` to see what was last committed.

## Step 3 — Locate the design spec (if starting a new feature)

Read `docs/design/README.md` to find the design doc for the current release, then read that doc's **Outcome** and **Implementation order** sections.

## Step 4 — Resolve design questions

```
get_decisions(query="<topic>")
```

Use this before making any architectural call that touches contracts, storage, ranking, or MCP surface. If a relevant ADR exists, follow it.

---

## While working

- Run `uv run pytest` after every change. Red tests block progress.
- Commit at logical checkpoints — one concern per commit, conventional-commit message.
- Follow `.handover/standards/coding-standards.md`. Key rules: contracts package is the only cross-module interface; no silent no-ops; every new flag warns to stderr if it has no effect.

## End of session — required before clearing chat

```python
save_observation(
    summary="<60+ char summary of what was done and why>",
    task_type="implement",   # or debug / review / handover
    files_touched=["packages/memory/src/memory/retriever.py", "..."],
    fix_summary="<optional: what was broken and how it was fixed>"
)
```

Then commit the `.md` file that `save_observation` wrote:

```
git add .context-router/memory/observations/
git commit -m "chore(memory): capture <brief topic> observation"
```

**You can clear the chat after this commit.** The next session recovers full context from `get_context_pack(mode="handover")` + `search_memory` in ~500 tokens.
