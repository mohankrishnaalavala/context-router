# Changelog

All notable changes to context-router are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [0.7.0] — 2026-04-16

Phase P2 — quality improvements and broader language coverage. 13 P2 items
shipped across three streams; 27 new tests, 659 total passing.

### Added
- **Community-aware ranking boost** (`packages/core/src/core/orchestrator.py`):
  the orchestrator now reads `Symbol.community_id` (populated by the
  union-find clustering in `graph_index.community`) and boosts candidates
  sharing the anchor's community by `+0.10` (capped at 1.0). Additive —
  no effect when no symbol has a community assigned. (P2-1)
- **Cost-aware budget enforcement** (`packages/ranking/src/ranking/ranker.py`):
  `_enforce_budget` replaced greedy confidence-desc admission with
  value-per-token ordering (`confidence / est_tokens`). Four high-value
  small items now beat one large low-value item under the same budget.
  `is_first_of_type` guarantee preserved; final emit order stays
  confidence-desc. (P2-2)
- **Configurable confidence weights** (`packages/contracts/src/contracts/config.py`,
  orchestrator): new optional `confidence_weights` block on
  `ContextRouterConfig`. Per-mode dicts merge over the hardcoded defaults,
  so partial overrides are safe. Absent config = prior behaviour. README
  "Advanced Configuration → Tuning confidence weights" documents the
  schema. (P2-11)
- **Java constructor extraction** (`packages/language-java/src/language_java/__init__.py`):
  new `constructor_declaration` branch emits `Symbol(kind="constructor")`.
  Dependency-injection constructors are now first-class graph nodes. (P2-3)
- **C# constructor extraction** (`packages/language-dotnet/src/language_dotnet/__init__.py`):
  matching `constructor_declaration` handler; inherits attribute
  extraction. ASP.NET Core DI constructors are now indexed. (P2-4)
- **Broad Java annotation surface** (`packages/language-java/src/language_java/__init__.py`):
  every annotation (Spring, JPA, JUnit, custom) is prefixed on the symbol
  signature — BM25 can now discover `@Transactional`, `@Async`,
  `@RestController`, `@Bean`, etc. without a whitelist.
  `_collect_annotations` now handles both the modifiers child (modern
  grammar) and preceding siblings (legacy grammar), plus
  `marker_annotation` nodes. (P2-5)
- **TypeScript enum extraction** (`packages/language-typescript/src/language_typescript/__init__.py`):
  new `enum_declaration` branch (`kind="enum"`), covering both `enum` and
  `const enum`. (P2-7)
- **TypeScript decorator extraction** (same file):
  `_collect_decorator_names` handles bare (`@Inject`), call-expression
  (`@Component({...})`), and member-expression (`@ng.Module()`) decorator
  forms. Decorator names are prefixed on class/method signatures so BM25
  surfaces Angular and NestJS structural metadata. (P2-8)
- **Per-language benchmark task suites** (`packages/benchmark/src/benchmark/task_suite.py`):
  `TASK_SUITE_TS_REACT` (React/Next.js), `TASK_SUITE_JAVA_SPRING` (Spring
  Boot), `TASK_SUITE_DOTNET` (ASP.NET Core) — ~15 tasks each covering all
  four modes. `get_task_suite(name)` resolves by name.
  `context-router benchmark run --task-suite {generic,typescript,java,dotnet}`
  selects the suite. (P2-9)
- **MCP tool schemas**: all 15 MCP tools now declare `"required"` arrays
  in their `inputSchema` (the 7 that omitted it now do so explicitly),
  and every tool publishes an `outputSchema` describing its return shape.
  `tools/list` response includes `outputSchema` so MCP clients can
  validate responses. (P2-12, P2-13)

### Changed
- **`get_adjacent_files` rewritten** (`packages/storage-sqlite/src/storage_sqlite/repositories.py`):
  the previous OR-joined subquery is now a two-branch UNION that hits
  `idx_edges_repo_from` and `idx_edges_repo_to` (from migration
  `0008_feedback_scope_indexes.sql`) directly. Result set identical;
  large-repo blast-radius computation no longer degrades to a scan. (P2-16)

### Notes
- Skipped as already-satisfied during Phase P1 work: **P2-10** (handover
  observations already freshness-ranked via
  `memory.freshness.score_for_pack`), **P2-14** (stdio already wrapped by
  the outer `main()` exception handler), **P2-15** (`get_all_edges`
  already has `WHERE repo=?`).
- Version bumped from `0.6.0` → `0.7.0` across all 19 workspace packages;
  no schema migration required (current schema version remains 9).

---

## [0.6.0] — Unreleased

### Added
- **BM25 query scoring** (`packages/ranking`): Replaced exact substring matching with inline Okapi BM25 scoring. `ContextRanker` now uses the formula `final_conf = min(0.95, 0.6 × structural_conf + 0.4 × bm25_score)`, where BM25 score is normalized across all candidates per-query. "authentication" now matches `AuthManager`, `verify_token`, and similar identifiers that substring matching missed. No new dependency — BM25 is ~50 lines of inline Python.
- **Call flow analysis** (`packages/core`, `packages/storage-sqlite`): Debug mode now walks `calls` edges up to 3 hops from `runtime_signal`/`changed_file` items. Callee files appear as `source_type=call_chain` with confidence that decays 30% per hop (depth 1 = 0.45, depth 2 ≈ 0.315, depth 3 ≈ 0.22). Surfaces code paths that lead to an error site without manual tracing.
- **`explain last-pack --show-call-chains`**: New flag on the `explain last-pack` CLI command that groups `call_chain` items under a labelled section, making it easy to distinguish structural candidates from inferred call-chain ones.
- **`EdgeRepository.get_call_chain_files()`** (`packages/storage-sqlite`): BFS traversal of `calls` edges up to configurable depth. Cycle-safe; returns `[(file_path, hop_depth), ...]`.
- **`files_read` on `PackFeedback`** (`packages/contracts`, `packages/storage-sqlite`): Agents can now report which files they actually consumed from a pack. Enables read-coverage analytics: after ≥ 5 reports with `files_read`, `feedback stats` shows `read_overlap_pct` (fraction of reads that were useful) and `noise_ratio_pct` (fraction of reads that were noisy).
- **Migration 0007** (`packages/storage-sqlite`): `ALTER TABLE pack_feedback ADD COLUMN files_read TEXT NOT NULL DEFAULT '[]'`.
- **`feedback record --files-read`**: New CLI flag (space-separated file paths) on the `feedback record` command.
- **`record_feedback` MCP tool updated**: Now accepts `files_read` parameter (array of strings).

### Changed
- `ContextRanker._apply_query_boost()` replaced by `_apply_bm25_boost()` — scoring formula changed from additive exact-match boost to weighted BM25 combination. Items with no query match get 60% of their structural confidence instead of 100%; query-relevant items can reach up to 0.95 regardless of structural tier.
- Test suite expanded to **~640 tests** (was 586 in v0.5.0).

---

## [0.5.0] — Unreleased

### Added
- **`format=compact` for context packs**: `get_context_pack` and `context-router pack` now accept `--format compact` / `format="compact"` returning `[conf] path\n  title\n  excerpt` lines — no JSON metadata overhead (UUID, freshness, tags). Agents that consume packs as text benefit from ~40 tokens/item reduction.
- **`get_context_summary` MCP tool (14th tool)**: Lightweight peek at a pack — returns mode, item count, token total, reduction %, top 5 files by confidence, and source type distribution in < 200 tokens. Use before `get_context_pack` to decide whether the full pack is needed.
- **Pagination for context packs**: `get_context_pack` and `context-router pack` now accept `page` (0-based) and `page_size` parameters. Response includes `has_more: bool` and `total_items: int` so agents can load 30 items at a time instead of 240+.
- **Auto-capture hooks**: `packages/core/src/core/hooks/post_commit.py` and `claude_code_hook.py` — installed by `context-router setup --with-hooks`. Post-commit hook captures commit message + changed files as a memory observation; Claude Code `PostToolUse` hook captures file edits. Both run silently and never block the git/agent workflow.
- **`setup --with-hooks` flag**: Installs git `post-commit` hook and Claude Code `PostToolUse` hook entry in `.claude/settings.json` — idempotent, dry-run safe.

### Fixed
- **`est_tokens` undercounting**: Previously only counted `excerpt` tokens; now includes `title` + 40-token fixed overhead per item (UUID, source_type, repo, path, reason, freshness, tags in JSON transport). Benchmark reduction percentages are now honest — previously overstated by ~40 tokens × item count.

### Changed
- MCP server now exposes **14 tools** (was 13 in v0.4.x): added `get_context_summary`
- Test suite expanded to **586 tests** (was 513 in v0.4.0)

---

## [0.4.0] — 2026-04-14

### Added
- **`setup` command**: One-command agent configuration — auto-detects Claude Code, GitHub Copilot, Cursor, Windsurf, and OpenAI Codex from existing config files and appends context-router instructions to the appropriate files (`CLAUDE.md`, `.mcp.json`, `.github/copilot-instructions.md`, `.cursorrules`, `.windsurfrules`, `AGENTS.md`). Idempotent and `--dry-run` safe. 29 new tests.
- **MCP auto-registration**: `setup --agent claude` adds the context-router MCP server entry to `.mcp.json`, enabling one-step Claude Code integration without manual JSON editing.
- **Homebrew tap**: `brew tap mohankrishnaalavala/context-router && brew install context-router` — auto-updates daily from PyPI via GitHub Actions.
- **Quality benchmark metrics**: `hit_rate`, `random_hit_rate`, `rank_quality` added to benchmark harness and all 20 tasks annotated with `expected_symbols`. Report shows hit rate vs random baseline per mode.
- **tiktoken token estimation**: Replaced `max(1, len(text) // 4)` with real `cl100k_base` BPE; graceful fallback if tiktoken unavailable. Emoji and Unicode now count accurately.
- **Benchmark metric definitions**: `BENCHMARK_RESULTS.md` documents every metric with formulas, confidence source table, and review-mode domain-mismatch explanation.

### Fixed
- **Query boost for low-confidence items**: `_apply_query_boost` now uses additive boost (`conf + ratio × 0.50`) for all confidence levels instead of multiplicative for items < 0.50. A `file`-category symbol (base 0.20) with a full query match reaches 0.70 — equal to `blast_radius` — so query-relevant symbols compete fairly with structurally-adjacent ones.

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
