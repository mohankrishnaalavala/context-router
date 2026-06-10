---
id: 2026-05-30-v445-packaging-hotfix-shipped-to-pr-1
type: observation
task: implement
files_touched:
  - apps/cli/pyproject.toml
  - Makefile
  - uv.lock
  - CHANGELOG.md
  - docs/release/v4-outcomes.yaml
  - .github/ISSUE_TEMPLATE/bug_report.yml
  - .github/ISSUE_TEMPLATE/feature_request.yml
  - .github/ISSUE_TEMPLATE/config.yml
  - SECURITY.md
  - CONTRIBUTING.md
  - README.md
created_at: 2026-05-30T19:10:43.058538+00:00
author: context-router
---

v4.4.5 packaging hotfix SHIPPED to PR #119 (develop->main), all CI green (Lint/Test/Build check = SUCCESS), MERGEABLE — NOT merged/tagged/released (awaiting user approval). Root cause of friend's install failure: apps/cli/pyproject.toml listed context-router-evaluation in [project].dependencies, but it's force-included into the CLI wheel and NOT published to PyPI, so clean installs (uv tool/pipx/pip) failed with "No matching distribution found for context-router-evaluation". Fix: removed that one dep line (eval/benchmark still ship via force-include and import fine — benchmark already followed this pattern). Also bumped all 27 packages 4.4.4->4.4.5, fixed make bump-version sed (was hardcoded 0.x.x), refreshed uv.lock, added v4.4.5-clean-install DoD to docs/release/v4-outcomes.yaml. Part B docs: .github/ISSUE_TEMPLATE/{bug_report,feature_request,config}.yml, SECURITY.md (GitHub private vulnerability reporting), CONTRIBUTING.md Reporting issues section, README Reporting issues & support section. Commits 52a5be8 (fix) + 0af4718 (docs). Verified via clean venv: built wheel with `uv build --package context-router-cli --wheel` (plain uv build w/o --wheel FAILS on force-includes via sdist path; release.yml already uses --wheel so CI is fine), pip install RC=0, context-router --version=4.4.5, index --json valid, MCP init version 4.4.5, suite 1465 passed/12 skipped. KNOWN PRE-EXISTING BUG (not mine, worth separate fix): scripts/smoke-packaging.sh fails with PARSE_ERROR because it captures `index --json` with 2>&1 and optional-parser WARN lines (go/rust/ruby/php tree-sitter absent in default install) precede the JSON, breaking json.loads. ENV LESSONS this session: (1) system python3 is 3.9.6 no tomllib — use `uv run python`; (2) the Claude session tmpfs (/private/tmp/claude-501/.../tasks) filled to ENOSPC and silently dropped/garbled ALL tool output for a long stretch, causing acting on fabricated results — `uv cache clean` + clearing task .output files fixed it; when output looks impossible, suspect full tmpfs not hallucination.
