# Changelog

All notable changes to context-router are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [0.2.2] — 2026-04-13

### Fixed
- **Missing `watchdog` dependency**: `graph_index.watcher` uses `watchdog>=4.0` which was not declared in the bundled wheel; added to `context-router-cli` dependencies

---

## [0.2.1] — 2026-04-13

### Fixed
- **PyPI install**: `pip install context-router-cli` now works — all workspace-internal sub-packages are bundled into the wheel via hatchling `force-include`; previously they were listed as dependencies that didn't exist on PyPI
- **Wheel-only build**: Release pipeline now uses `--wheel` flag (no sdist) to correctly resolve bundled source paths
- **Python version clarity**: Package requires Python ≥ 3.12; install via `uv tool install context-router-cli` to use uv's managed Python automatically

---

## [0.2.0] — 2026-04-13

### Added
- **CALLS edges**: Python analyzer now emits `DependencyEdge(edge_type="calls")` for function-level call sites (tracked via `current_func` AST walk parameter)
- **TESTED_BY edges**: Post-indexing pass links `test_foo()` → `foo()` via name-stripping heuristic; stored with `edge_type="tested_by"`
- **Semantic ranking**: `ContextRanker(use_embeddings=True)` uses `sentence-transformers/all-MiniLM-L6-v2` for cosine-similarity boosting — opt-in, no API key, runs locally
- **Community detection**: Union-Find on the symbol graph after indexing; `community_id` stored per symbol, exposed in graph visualization
- **TypeScript/JavaScript analyzer**: `context-router-language-typescript` package using `tree-sitter-typescript`; registers as `ts` and `js` entry points
- **Graph visualization community toggle**: `context-router graph` HTML now supports "Color by: kind / community" toggle

---

## [0.1.0] — 2026-04-12

### Added
- **Graph visualization**: `context-router graph [--output PATH] [--open]` — self-contained D3.js v7 force-directed HTML (701 nodes, 176 edges on context-router itself)
- **6 quality fixes**:
  - FTS5 JOIN fix: `o.rowid` not `o.id` — `decisions search` and `memory search` now return results
  - Entrypoint guard: test/fix/setup/migration files no longer assigned `source_type=entrypoint`
  - Config confidence: 0.40 → 0.25 so config files don't crowd out code symbols
  - Dynamic token budget: `min(config_budget, max(1000, baseline//2))` for ≥50% reduction on small repos
  - Filename boost: query mentions of `ranker.py` etc. boost matching items by +0.40
  - Query boost ceiling: `_MAX_BOOST` raised 0.30→0.50, multiplicative path for low-confidence items

### Added (Phase 7–8)
- Multi-repo workspace: `workspace.yaml`, `WorkspaceOrchestrator`, cross-repo link detection
- CLI: `context-router workspace init/repo add/repo list/link add/pack`
- Benchmark harness: 20-task suite (5 per mode), JSON + Markdown reporters
- CLI: `context-router benchmark run/report`

### Added (Phase 5–6)
- MCP server: `context-router mcp` — stdio JSON-RPC, compatible with Claude Desktop
- Agent adapters: Claude (Anthropic SDK), GitHub Copilot (LSP), Codex (OpenAI SDK)

### Added (Phase 3–4)
- Debug mode: runtime signals, stack trace parser (Python/Java/.NET), pytest XML ingestion
- Memory layer: `context-router memory add/list/search` — durable session observations
- Decisions layer: `context-router decisions add/list/search` — architectural decision records

### Added (Phase 1–2)
- Indexing pipeline: Python analyzer (tree-sitter), YAML analyzer, graph writer
- Context packs: review/implement/debug/handover modes with confidence scoring
- Token budget enforcement with per-source-type guarantees
- Import noise elimination: imports → `DependencyEdge`, YAML generic keys removed

### Added (Phase 0)
- Monorepo workspace with 16 packages under `uv`
- Pydantic contracts: ContextItem, ContextPack, Observation, Decision, RuntimeSignal
- SQLite storage with FTS5 for memory and decisions search
- CLI shell: all commands, `--help` works
- pytest harness: 372 tests

---

## Release Process

See [RELEASE.md](RELEASE.md) for step-by-step release instructions.
