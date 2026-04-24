# Session Prompt — Implement

Use this prompt to start an implementation session for **OSS Project Plan**.

---

You are working on **OSS Project Plan**.

Before writing any code:

1. Read `.handover/context/overview.md` and `.handover/context/architecture.md`.
2. Read `.handover/work/spec.md` for the full feature specification.
3. Pick the next unchecked task from `.handover/work/tasks.md` (or take one
   from `.handover/work/backlog.json`).
4. Check `.handover/standards/coding-standards.md` and
   `.handover/standards/testing-standards.md` before producing changes.
5. Respect everything in `.handover/context/constraints.md` and
   `.handover/context/decisions.md`.

While implementing:

- Make a plan, then execute one task at a time.
- Run the project's tests after each change. Do not move on if they fail.
- When a task is finished, tick it off in `.handover/work/tasks.md` and set
  `done: true` in `.handover/work/backlog.json`.

Stop and ask the user when:

- A constraint or decision blocks the obvious approach.
- A task description is ambiguous.
- You hit an open question listed in `.handover/context/risks.md`.