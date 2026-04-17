# Definition of Done — template

Every feature spec copies this block verbatim and fills in all four fields **before any code is written**. A spec without a filled DoD is not mergeable.

The rule: each field describes a user-visible effect, not an implementation detail. "Function X returns Y" is not a DoD. "When the user runs `context-router pack --with-semantic` outside `implement` mode, stderr contains `--with-semantic has no effect in <mode> mode`" is a DoD.

```yaml
dod:
  # What the user sees when the feature works. One sentence, no code, no file paths.
  outcome: >-
    <user-visible outcome>

  # A numeric threshold or a diff. If you can't measure it, pick something observable.
  threshold: >-
    <e.g. "second CLI invocation runs in <50% of first invocation's wall time"
          or "pack output contains each symbol at most once"
          or "--help shows a line matching 'context-router 3\\.0\\.\\d+'">

  # What MUST happen on bad input, the wrong mode, or a failure path.
  # Silent no-ops are a bug. If the feature is inactive, emit a warning.
  negative_case: >-
    <e.g. "passing --with-semantic in handover mode writes
           'warning: --with-semantic has no effect in handover mode' to stderr
           and exits 0">

  # Exact command + expected stdout substring. Goes into docs/release/v3-outcomes.yaml.
  verify:
    cmd: >-
      <shell command>
    expected_stdout_contains: >-
      <substring — be specific, not 'Success'>
```

## Worked examples

### P0-1 — CLI table dedup

```yaml
dod:
  outcome: >-
    The pack CLI table shows each symbol at most once.
  threshold: >-
    For the query "add pagination" against bulletproof-react, the `Pagination`
    row appears exactly once (not 3×).
  negative_case: >-
    If a duplicate would otherwise be emitted, the de-dup logic is silent
    (no warning) — but the pack-build metric counts de-duped rows so regressions
    surface in benchmarks.
  verify:
    cmd: >-
      context-router pack --mode implement --query "add pagination" --project-root fixtures/bulletproof-react
        | awk '/Pagination/ && !seen[$0]++'
    expected_stdout_contains: "Pagination"
```

### --version CLI flag

```yaml
dod:
  outcome: >-
    `context-router --version` prints the installed version and exits 0.
  threshold: >-
    Output matches /^context-router \d+\.\d+\.\d+/.
  negative_case: >-
    `context-router --version --help` still shows help (standard typer behavior).
  verify:
    cmd: >-
      context-router --version
    expected_stdout_contains: "context-router 3."
```
