# Session Prompt — Continue After a Gap

Use this prompt to resume work on **OSS Project Plan** after
time away.

---

You are resuming work on **OSS Project Plan**.

Catch up in this order:

1. Read `HANDOVER.md` if it exists at the project root — it captures the
   most recent session's state, files changed, and recommended next steps.
2. Re-read `.handover/work/tasks.md` and look at which boxes are checked.
3. Check `.handover/work/backlog.json` for any tasks marked
   `done: true` since the last time you worked.
4. Read `.handover/context/decisions.md` — there may be new ADRs.
5. Look at recent commits: `git log --oneline -20`.

Then:

- Pick the next unchecked task.
- Start a new implementation session using
  `.handover/prompts/implement.md`.

If the project was last touched a long time ago, also re-read the full
`.handover/context/` directory before doing anything.