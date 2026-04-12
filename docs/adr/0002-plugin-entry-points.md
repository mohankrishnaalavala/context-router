# ADR-0002: Language analyzer discovery via importlib.metadata entry_points

**Status:** Accepted  
**Date:** 2024-01

## Context

context-router needs to support multiple language analyzers (Python, Java,
C#/.NET, YAML) and must allow new languages to be added without modifying
core or storage code. We considered:

- Hardcoded registry in `core`
- Config file listing analyzer module paths
- Python entry_points (`importlib.metadata`)
- Abstract base class with manual registration

## Decision

Use Python's `importlib.metadata.entry_points(group="context_router.language_analyzers")`
for plugin discovery. Each language package registers itself with a key equal
to the file extension (without the leading dot).

Example in `language-python/pyproject.toml`:
```toml
[project.entry-points."context_router.language_analyzers"]
py = "language_python:PythonAnalyzer"
```

## Consequences

**Positive:**
- New languages can be added as independent packages without touching `core`
- Follows Python packaging conventions — no custom plugin protocol needed
- PluginLoader validates conformance to `LanguageAnalyzer` protocol via `isinstance`
  (enabled by `@runtime_checkable`)
- Works in both installed and editable (`uv sync`) mode

**Negative:**
- Plugins must be installed as packages; running analyzers from a source directory
  without installing requires `uv sync` or `pip install -e .`
- Entry point registration only takes effect after the package is installed;
  this is expected behavior and documented in the setup guide

**Key convention:** Extension keys must be registered WITHOUT the leading dot
(`py`, not `.py`). `PluginLoader.get_analyzer()` takes the extension without
the dot.
