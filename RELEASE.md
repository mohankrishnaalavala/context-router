# Release Process

This document describes how to cut a release of context-router.

---

## Versioning

context-router uses [Semantic Versioning](https://semver.org/):
- **MAJOR** (1.x.x): breaking changes to contracts, CLI flags, or MCP protocol
- **MINOR** (0.x.0): new features, new language analyzers, new CLI commands
- **PATCH** (0.0.x): bug fixes, performance improvements, documentation

All packages share the same version number. Update it in every `pyproject.toml`.

---

## Release Checklist

Run this checklist before every release. Each item maps to a step below.

### Pre-release

- [ ] **All tests pass** — `uv run pytest --tb=short -q` → 0 failures
- [ ] **Import boundary check** — `uv run python -c "import contracts"` (CI enforces this)
- [ ] **CHANGELOG updated** — move `[Unreleased]` items to a versioned section
- [ ] **Version bumped** — all `pyproject.toml` files updated (see "Bump version" below)
- [ ] **README updated** — feature table, install instructions, any new commands documented
- [ ] **Benchmark results updated** — run `bash benchmark/run-holdout.sh ...` (and/or `context-router benchmark run`) and update `BENCHMARKS.md` + `benchmarks/results/<date>-<version>/`
- [ ] **No TODO/FIXME left in release-critical paths** — `grep -r "TODO\|FIXME" packages/core packages/contracts packages/ranking`

### Release

- [ ] **Commit** — `git commit -m "chore: release v0.x.y"`
- [ ] **Tag** — `git tag -a v0.x.y -m "Release v0.x.y"`
- [ ] **Push tag** — `git push origin v0.x.y`
- [ ] **GitHub Release** — `gh release create v0.x.y --title "v0.x.y" --notes-file release-notes.md`
- [ ] **PyPI publish** (when ready) — `uv build && uv publish`

### Post-release

- [ ] **Verify CI green** on the release tag
- [ ] **Update memory** — save new project state to `.claude/projects/*/memory/project_state.md`
- [ ] **Close milestone** on GitHub (if using milestones)

---

## Bump Version

The version appears in every `pyproject.toml`. Use this script to bump all at once:

```bash
NEW_VERSION="0.2.0"
find . -name "pyproject.toml" -not -path "*/\.*" | while read f; do
    sed -i '' "s/^version = \"0\.[0-9]*\.[0-9]*\"/version = \"$NEW_VERSION\"/" "$f"
done
# Verify
grep -r "^version = " packages/*/pyproject.toml apps/*/pyproject.toml
```

---

## Agent Release Checklist

You can ask the Claude Code agent to run the release checklist automatically:

```
/release-check
```

Or manually prompt:
```
Run the release checklist for context-router v0.2.0:
1. Run tests and report failures
2. Check CHANGELOG has Unreleased items to move
3. Verify README mentions all new commands (graph, workspace, benchmark)
4. Run benchmark and summarize token reduction numbers
5. Check for any TODO/FIXME in core packages
6. Report what's missing before we can tag
```

---

## Package Structure

When we publish to PyPI (future), each package publishes separately:

| PyPI name | Source |
|---|---|
| `context-router` | `apps/cli` (the main user-facing package) |
| `context-router-contracts` | `packages/contracts` |
| `context-router-core` | `packages/core` |
| `context-router-language-python` | `packages/language-python` |
| `context-router-language-typescript` | `packages/language-typescript` |
| `context-router-language-yaml` | `packages/language-yaml` |
| `context-router-ranking` | `packages/ranking` |
| `context-router-storage-sqlite` | `packages/storage-sqlite` |
| `context-router-graph-index` | `packages/graph-index` |
| `context-router-memory` | `packages/memory` |
| `context-router-runtime` | `packages/runtime` |
| `context-router-workspace` | `packages/workspace` |
| `context-router-benchmark` | `packages/benchmark` |

The CLI (`apps/cli`) depends on all others — install it and you get everything:
```bash
pip install context-router
```

---

## GitHub Actions Release Workflow (future)

Add `.github/workflows/release.yml`:

```yaml
on:
  push:
    tags: ["v*"]

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-packages --extra dev
      - run: uv run pytest --tb=short -q
      - run: uv build
      - run: uv publish
        env:
          UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}
```
