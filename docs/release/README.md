# Release quality process

Everything in this folder is the **source of truth** for how a feature becomes part of a context-router release. The policy is mandatory; see `CLAUDE.md` for the enforcement rule.

## Why this exists

v2.0.0 shipped with visible P0 bugs (pack dedup, mis-labelled symbol kinds), a non-functional cache, and a silent `--with-semantic` flag — each of which had green unit tests. The root cause: specs measured code, not outcomes. This process closes that gap.

## Documents

| File | Purpose |
|---|---|
| `dod-template.md` | Every spec copies this block verbatim. No code starts without a filled-in DoD. |
| `v3-outcomes.yaml` | Single source of truth for every v3 feature's user-visible outcome + verification command. Drives the smoke script and the ship-check skill. |
| `../../scripts/smoke-v3.sh` | Executable smoke that reads the registry, runs each `verify_cmd`, diffs against `expected_stdout_contains`. |

## Flow for a new feature

1. **Write DoD** — copy `dod-template.md` into the spec. All four fields filled, or the spec is not mergeable.
2. **Add to registry** — append an entry to `v3-outcomes.yaml` with the outcome, verify command, and expected output substring.
3. **Implement + test** as usual.
4. **Run ship-check** — invoke the `ship-check` skill (or `/ship-check` slash command). It runs the smoke, verifies registry coverage, and writes a report to `internal_docs/ship-check/reports/` (gitignored).
5. **Paste the ship-check verdict into the PR body.** No verdict → no merge.
6. **Per-phase re-review** — at the end of each phase (not just the release), run the 7-prompt playbook. Reports go to `internal_docs/ship-check/per-phase-reviews/` (gitignored).

## Generated artifacts location

All generated outputs live under `internal_docs/ship-check/` which is gitignored. The policy files (this folder, the skill, the command, the script) are tracked.
