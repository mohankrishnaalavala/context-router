---
name: ship-check
description: Run the v3 ship-check quality gate — smoke, silent-failure audit, verdict
---

# /ship-check

Run the mandatory feature quality gate and produce a verdict paste-ready for the PR body.

## Steps

1. **Coverage check** — list every id in `docs/release/v3-outcomes.yaml`. Cross-reference the items this branch claims to address against the priority queue in `internal_docs/production-readiness-review-v2.md`. Any user-visible surface on the branch that is not in the registry → **BLOCK** (tell the user which entry to add).

2. **Smoke run** — execute `scripts/smoke-v3.sh report`. Show the user the path of the written report and the final summary line.

3. **Silent-failure audit** — for each flag / mode / tool this branch touches, run one intentionally-wrong invocation (wrong mode, bad input, missing prerequisite). If stderr is empty, that's a BLOCK: silent no-ops are bugs.

4. **Cross-feature interaction** — pick one real fixture from `${PROJECT_CONTEXT_ROOT}/{bulletproof-react,eShopOnWeb,spring-petclinic}` and run at least one combined invocation exercising this feature alongside others it touches. Paste the stdout.

5. **Verdict** — print the PASS/BLOCK block from `.claude/skills/ship-check/SKILL.md` step 5. Always include the report file path.

## Rules

- Do not mark the verdict PASS unless you actually ran the smoke and saw the report. "Tests pass" is not ship-check pass.
- Do not auto-fix findings during ship-check — file them as follow-ups. Ship-check's job is to tell the truth about release state, not to hide it.
- If this is the end of a phase (not a single-feature PR), also run the 7-prompt playbook per `.claude/skills/ship-check/SKILL.md` step 6.
