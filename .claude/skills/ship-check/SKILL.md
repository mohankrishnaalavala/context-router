---
name: ship-check
description: Mandatory quality gate that every feature must pass before being declared done. Runs the smoke registry and writes a verdict to internal_docs/ship-check/.
---

# ship-check — the feature done-gate

> **This skill is mandatory.** No feature is "done" until ship-check returns PASS and the verdict is pasted into the PR body. CLAUDE.md enforces this.

## Why this exists

v2.0.0 shipped TTLCache (useless in CLI), silent `--with-semantic`, pack dedup bug, and mis-labelled symbol kinds. Every one had green unit tests. The gap: tests checked code; nothing checked user-visible outcomes. ship-check closes that gap.

## When to invoke

Invoke this skill:

1. **Before opening a PR** for any feature that adds, changes, or removes user-visible behavior (CLI flag, MCP tool, pack field, indexing output, benchmark output).
2. **Before declaring "done"** in any task response to the user.
3. **At the end of each phase** during a multi-phase release (e.g. Phase 1 of v3). This is the per-phase re-review — not just at release time.
4. **Whenever the user runs `/ship-check`.**

You do NOT need to invoke this skill for:
- Pure internal refactors with no user-visible effect.
- Documentation-only changes.
- Test-only additions.

If you're uncertain, invoke it. False positives are cheap; shipping a silent bug is not.

## Procedure

### 1. Check registry coverage

For every item in `internal_docs/production-readiness-review-v2.md`'s priority queue that the current branch claims to address, confirm there's a matching entry in `docs/release/v3-outcomes.yaml`. Missing entry = FAIL (block the feature until the entry is written).

```bash
# Cross-reference: items this branch touches vs registry ids
grep -nE '^\| [0-9]' internal_docs/production-readiness-review-v2.md
grep -nE '^  - id:' docs/release/v3-outcomes.yaml
```

For any feature NOT in the priority queue but still user-visible (e.g. a new flag), it must be added to `v3-outcomes.yaml` before ship-check passes.

### 2. Run the smoke

```bash
scripts/smoke-v3.sh report
```

The report goes to `internal_docs/ship-check/reports/smoke-<timestamp>.md` (gitignored). Read the report. Every outcome touched by this feature must be PASS. Unrelated FAILs from unimplemented features are expected — note them but don't block on them unless this feature is the one supposed to implement them.

### 3. Silent-failure audit

Run the feature's no-op / wrong-mode / bad-input paths by hand. For each:
- If the feature is intentionally inactive, it MUST print a warning to stderr naming the reason. Silent no-ops are a bug regardless of how much test coverage they have.
- Paste the output of 2–3 negative-case invocations into the PR description.

### 4. Cross-feature interaction check

If the feature interacts with other v3 features (e.g. `--with-semantic` + cache + progress + MCP), run at least one combo against a real fixture repo (bulletproof-react / eShopOnWeb / spring-petclinic). Paste stdout into the PR.

### 5. Write the verdict

Produce a block that looks like this and paste it into the PR body:

```markdown
## Ship-check verdict

- Registry coverage: ✅ all touched items present
- Smoke: ✅ PASS (report: internal_docs/ship-check/reports/smoke-<ts>.md)
- Silent-failure audit: ✅ `--with-semantic` in handover mode emits `warning: --with-semantic has no effect in handover mode`
- Cross-feature interaction: ✅ `pack --mode implement --with-semantic --progress` against bulletproof-react produces expected output
- Unrelated FAILs in report: 3 (items 11, 12, 13 — not in this PR's scope)

Verdict: **PASS — safe to merge**
```

If any check fails, the verdict is **BLOCK** and you must explain what's still needed.

### 6. Per-phase re-review (release-only)

After each phase lands on `develop`, run the 7-prompt playbook (`internal_docs/context-router-prompt-playbook.md`) scoped to that phase's changes. Dispatch each prompt as a separate agent. Collect findings under `internal_docs/ship-check/per-phase-reviews/phase-N/` (gitignored). Do NOT proceed to the next phase until each P0/P1 item surfaced is either fixed or explicitly deferred with a dated rationale.

## What counts as a release blocker

| Signal | Verdict |
|---|---|
| Any P0 outcome in registry = FAIL | BLOCK |
| Any outcome this PR claims to implement = FAIL | BLOCK |
| Silent no-op on a flag/mode | BLOCK |
| Registry missing an entry for a new user-visible surface | BLOCK |
| FAILs in unrelated outcomes | NOTE, don't block |
| Per-phase re-review surfaces a new P0 | BLOCK next phase |

## Do not

- **Do not** downgrade the gate because tests are green. Tests are necessary, not sufficient.
- **Do not** skip the silent-failure audit. It's the class of bug that shipped three times in v2.0.
- **Do not** edit `v3-outcomes.yaml` to match the feature after the fact without updating the spec too — the registry is the contract, not a log of what happened.
- **Do not** paste a PASS verdict without actually running the smoke. If the smoke didn't run, the verdict is UNKNOWN, not PASS.
