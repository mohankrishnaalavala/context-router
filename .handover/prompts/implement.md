# Implement — context-router

Use this prompt when starting an implementation session for a specific task or feature.

---

## Step 1 — Load task context via context-router MCP

```
get_context_pack(mode="implement", query="<task description, e.g. staleness detection for memory observations>")
```

This returns the ranked, token-budgeted set of files most relevant to the task. Read these before opening anything else.

## Step 2 — Read the design spec

Open `docs/design/README.md` and find the design doc for the current release. Read:

- **Outcome** — what the user can do when this is done
- **DoD** — the exact verify command and expected output
- **Implementation order** — which phase to work on next
- **ADRs** — constraints that apply to this task

## Step 3 — Confirm the DoD entry exists

Open `docs/release/v4-outcomes.yaml`. Find the entry for this task. If it is missing, add it (copying `docs/release/dod-template.md`) before writing any code. A spec without a DoD entry is not mergeable.

## Step 4 — Baseline green

```
uv run pytest
```

Confirm all tests pass before touching anything. Record any pre-existing failures if found.

## Step 5 — Check constraints and past decisions

```
get_decisions(query="<task topic>")
```

Check `.handover/context/constraints.md` for any hard constraint that affects this task (e.g. no API key, no business logic in CLI/MCP layers, all storage via repository interfaces).

---

## While implementing

- One logical change per commit. Conventional-commit format (`feat:`, `fix:`, `test:`, `chore:`).
- `uv run pytest` after every non-trivial change. Do not stack unverified changes.
- No silent no-ops — any flag or mode with no effect in a context MUST warn to stderr.
- Every new `ContextItem` or `MemoryHit` field must be present in the contracts package before any other package uses it.
- If a task is ambiguous or hits an open question in `.handover/context/risks.md`, stop and ask before guessing.

## Before opening a PR

1. Run `/ship-check` — paste the full verdict block into the PR body. No verdict = no merge.
2. Confirm CI is green after pushing to `develop`.
3. Confirm the DoD `verify.cmd` in `v4-outcomes.yaml` passes locally.

## End of session

```python
save_observation(
    summary="<what was implemented and any non-obvious decisions made>",
    task_type="implement",
    files_touched=["<list of files changed>"],
    fix_summary="<if a bug was fixed: root cause and fix>"
)
```

Commit the observation file, then push. You can clear the chat — the next session recovers from `get_context_pack` + `search_memory`.
