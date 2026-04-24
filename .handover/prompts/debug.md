# Session Prompt — Debug

Use this prompt to start a debugging session for **OSS Project Plan**.

---

You are debugging **OSS Project Plan**.

Workflow:

1. Reproduce the bug. Capture the exact failing input and the actual vs.
   expected output. If you cannot reproduce it, stop and ask.
2. Read `.handover/context/architecture.md` so you understand which
   component owns the failing code path.
3. Form a hypothesis. Test it with the smallest possible change.
4. Add a regression test (per
   `.handover/standards/testing-standards.md`) **before** the fix.
5. Apply the fix. Run the full test suite.
6. Update `.handover/context/decisions.md` if the fix changes a documented
   behavior, and update `.handover/context/risks.md` if a new risk emerged.

Never:

- Suppress an error to make a test pass.
- Disable a failing test.
- Bypass safety checks (`--no-verify`, `--force`, etc.) without approval.