# Session Prompt — Write Tests

Use this prompt to start a test-writing session for **OSS Project Plan**.

---

You are writing tests for **OSS Project Plan**.

Reference material:

- `.handover/context/acceptance-criteria.md` — what "done" means.
- `.handover/standards/testing-standards.md` — the testing bar.
- `.handover/work/spec.md` — the feature you are testing.

Process:

1. Identify the smallest behavior worth testing.
2. Write a failing test first.
3. Run only the new test, confirm it fails for the right reason.
4. Implement (or wait for the implementation), then re-run.
5. Add edge cases: empty input, invalid input, boundary values, error paths.
6. Verify coverage does not regress.

Do not:

- Write tests that exercise mocks instead of behavior.
- Skip error-path tests.
- Add fixtures that hide assumptions about the system under test.