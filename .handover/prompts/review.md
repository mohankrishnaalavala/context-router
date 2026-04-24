# Session Prompt — Review

Use this prompt to start a code review session for **OSS Project Plan**.

---

You are reviewing changes to **OSS Project Plan**.

Reference material:

- `.handover/context/architecture.md` — what the system is supposed to look like.
- `.handover/context/decisions.md` — the design decisions every change must respect.
- `.handover/context/constraints.md` — the hard requirements.
- `.handover/standards/coding-standards.md` — the style and structure rules.
- `.handover/standards/testing-standards.md` — the testing bar.
- `.handover/standards/security-guardrails.md` — security do/don't.

For each change, answer:

1. Does it respect the architecture and decisions?
2. Does it violate any constraint?
3. Are tests added and meaningful?
4. Are there security or performance regressions?
5. Is the code easy to read and maintain?

Be specific. Cite file paths and line numbers. Suggest concrete fixes.