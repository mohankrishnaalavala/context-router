# Contributing to context-router

## Development setup

Python 3.12+ is required.

```bash
git clone https://github.com/mohankrishnaalavala/context-router
cd context-router
uv sync --all-packages --extra dev
```

Run the full test suite:

```bash
uv run pytest
```

## Project layout

```
packages/   # Libraries with strict import boundaries
apps/       # CLI (apps/cli) and MCP server (apps/mcp-server)
```

Each package under `packages/` has a single responsibility. `contracts` defines shared types and plugin protocols; no internal package may import from another package's internals — only from `contracts`. See `.handover/context/architecture.md` for the full dependency graph.

## Adding a language analyzer

A language analyzer is a Python package that implements the `LanguageAnalyzer` protocol from `packages/contracts/src/contracts/interfaces.py`:

```python
from pathlib import Path
from contracts.interfaces import LanguageAnalyzer, Symbol, DependencyEdge

class RustAnalyzer:
    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a source file and return normalized symbols and edges."""
        ...
```

The method must return `Symbol` or `DependencyEdge` instances — never raw Tree-sitter nodes.

Register the analyzer via entry points in your `pyproject.toml`:

```toml
[project.entry-points."context_router.language_analyzers"]
rs = "my_package.analyzer:RustAnalyzer"
```

The key is the file extension without the leading dot (`py`, `rs`, `go`). After `uv sync`, `context-router index` discovers and loads it automatically.

See `packages/language-python/` for a full reference implementation.

## PR process

1. Open an issue before starting non-trivial work so the approach can be agreed on.
2. One feature or fix per PR; keep diffs small and reviewable.
3. All tests must pass: `uv run pytest`.
4. Update `CHANGELOG.md` for any user-visible change.

## Testing

Run the full suite:

```bash
uv run pytest
```

Run tests for one package only:

```bash
uv run pytest packages/language-python/ -x -q
```

## Commit style

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat:      new user-visible feature
fix:       bug fix
docs:      documentation only
refactor:  code change with no behavior change
test:      add or update tests
chore:     tooling, deps, CI
```

Example: `feat(ranking): add BM25 query scoring`
