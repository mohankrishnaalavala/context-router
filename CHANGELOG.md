# Changelog

All notable changes to context-router are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- **`setup` command**: One-command agent configuration — auto-detects Claude Code, GitHub Copilot, Cursor, Windsurf, and OpenAI Codex from existing config files and appends context-router instructions to the appropriate files (`CLAUDE.md`, `.mcp.json`, `.github/copilot-instructions.md`, `.cursorrules`, `.windsurfrules`, `AGENTS.md`). Idempotent and `--dry-run` safe.
- **MCP auto-registration**: `setup --agent claude` adds the context-router MCP server entry to `.mcp.json`, enabling one-step Claude Code integration without manual JSON editing.
- **Homebrew tap**: `brew tap mohankrishnaalavala/context-router && brew install context-router` — formula in `docs/homebrew-formula.rb`.
- **Homebrew tap formula** (`docs/homebrew-formula.rb`): ready-to-publish virtualenv formula for `mohankrishnaalavala/homebrew-context-router` tap.

---

## [0.3.0] — 2026-04-13

### Added
- **Java analyzer (full)**: `language-java` now emits `DependencyEdge` for `import` statements, function-level call edges, and JavaDoc docstrings — previously a stub
- **C#/.NET analyzer (full)**: `language-dotnet` now emits `DependencyEdge` for `using` directives, call edges, C# attributes in signatures — previously a stub
- **YAML GHA `needs` edges**: GitHub Actions workflow files emit `needs` dependency edges between jobs; Docker Compose `depends_on` edges also captured; real line numbers on all YAML symbols
- **Memory freshness scoring**: `effective_confidence = min(0.95, confidence × decay + access_boost)` — 30-day half-life decay, +0.02 per search access (capped +0.20); stale observations fade naturally
- **`memory list`**: List observations sorted by `freshness`, `recency`, or `confidence` with `--limit`
- **`decisions supersede`**: Link an old decision to its replacement; superseded decisions show "Superseded by" in export
- **`memory export`**: Export all observations to a single Markdown file; `--redacted` strips file paths and commit SHAs
- **`decisions export`**: Export accepted decisions as individual ADR `.md` files (`0001-title-slug.md`); filterable by status
- **Debug memory — `error_hash`**: Normalized SHA256[:16] of exception type + message (strips line numbers and memory addresses) stored on `RuntimeSignal`; stable across re-runs of the same error
- **Debug memory — `top_frames`**: Structured `{"file", "function", "line"}` dicts extracted from Python and Java stack traces (top 5 frames)
- **Debug memory — `past_debug` tier**: On second occurrence of the same `error_hash`, files from the prior fix's stack trace are surfaced with confidence 0.90 — before generic blast-radius candidates
- **JUnit XML `failing_tests`**: `parse_junit_xml` now populates `failing_tests` with `classname.testname` format and computes `error_hash` per failure
- **`PackFeedback` model**: Agents record whether a pack was useful, which files were missing, and which were noisy
- **`feedback record/stats/list`** CLI: persist feedback, view aggregate usefulness %, top missing/noisy files
- **`record_feedback` MCP tool**: 13th MCP tool — agents call this after consuming a pack to drive continuous improvement
- **Feedback-adjusted confidence**: Files reported missing ≥3 times get +0.05 boost; noisy ≥3 times get −0.10 penalty — applied at pack-build time
- **`list_memory` MCP tool**: Browse observations by freshness score (12th tool)
- **`mark_decision_superseded` MCP tool**: Link old → new decision from MCP (was already in CLI)

### Changed
- MCP server now exposes **13 tools** (was 10 in v0.2.x): added `list_memory`, `mark_decision_superseded`, `record_feedback`
- SQLite schema bumped to **version 6** (migrations 0005 adds `error_hash`/`top_frames`/`failing_tests` columns; 0006 adds `pack_feedback` table)
- Test suite expanded to **513 tests** (was 372 in v0.1.0)

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
