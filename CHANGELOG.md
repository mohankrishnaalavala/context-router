# Changelog

All notable changes to context-router are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

---

## [4.1.0] — 2026-04-24

### Added
- `save_observation` now dual-writes: SQLite (primary) + git-tracked Markdown file under `.context-router/memory/observations/{date}-{slug}.md` with YAML frontmatter.
- Write gate: rejects observations with `summary < 60 chars` or empty `files_touched`, printing an explicit stderr warning instead of silently no-oping.
- `pack --use-memory` / MCP `get_context_pack use_memory: true` — injects up to 8 BM25+recency-ranked memory hits into every context pack, exposed as `memory_hits` in JSON output.
- `memory show <id>` — look up a saved observation by exact or prefix ID.
- `memory migrate-from-sqlite` — backfill all existing SQLite observations into git-tracked `.md` files.
- `NOTICE` file (Apache 2.0 attribution).

### Fixed
- **Ranking regression (file-level dedup):** `_dedup_by_file()` now collapses multiple symbols from the same file into the highest-confidence representative before budget enforcement, preventing duplicate `path_or_ref` entries from filling the top-k window.
- **BM25 CamelCase tokenization:** `_tokenize()` splits `OAuth2PasswordBearer` → `{"oauth2", "password", "bearer"}` so camel-case symbol names match query terms correctly.
- **Test-file ranking:** source files score 1.18× higher than test/script files in `review` and `implement` modes via a 0.85× confidence penalty on test paths (no penalty in `debug` mode).

### Changed
- License changed from MIT to Apache 2.0.
- BM25 corpus now includes the file basename alongside title and excerpt for better filename-query matching.

---

## [4.0.0] — 2026-04-23

### Added
- `context-router eval --queries <path>` subcommand: Recall@K / Precision@K / F1@K evaluation harness.
- `context-router workspace sync`: rebuild the cross-repo edge cache into `.context-router/workspace.db`.
- `.context-router/workspace.db` at workspace root — stores `repo_registry` + `cross_repo_edges` (ADR §7.4).
- Synthetic workspace fixture under `tests/fixtures/workspaces/synthetic/` with 10 queries.
- `scripts/fetch-benchmark-repos.sh` clones 3 real OSS repos at pinned SHAs for nightly evaluation.
- CI workflow `eval-synthetic` enforces `Recall@20 >= 0.65` on every PR.

### Changed
- `WorkspaceOrchestrator` exposes `cross_repo_edges_for_repo(repo_id)` — reads from `workspace.db` instead of recomputing at pack time.
- `get_context_pack` MCP tool accepts `use_workspace: bool` (default `false`) — when true, routes through `WorkspaceOrchestrator`.
- Reconcile is per-repo scoped; a change in one repo no longer rescans siblings.

### Fixed
- `context-router eval` runner now resolves `fixture_root` to absolute path before stripping pack result paths (was returning 0.0 recall despite correct files in pack).
- `context-router eval` CLI: `pack.selected_items` was referenced as `pack.items` (AttributeError on run).

---

## [3.3.1] — 2026-04-20

Hotfix: bundled MCP server could not start after `pip install context-router-cli`.

### Fixed

- **MCP server bundled in `context-router-cli` wheel now starts.** `mcp_server/main.py` resolved `serverInfo.version` from PyPI distribution `context-router-mcp-server`, which is never published to PyPI — only `context-router-cli` is. On any fresh `pip install` / `pipx install` / `brew install`, the module crashed at import time with `PackageNotFoundError` before a single JSON-RPC frame could be read, making `context-router mcp` unusable for every end‑user install path. Fix: fall back to `context-router-cli`'s distribution version when `context-router-mcp-server` is absent (release process bumps both in lockstep, so either's version is truthful). Source‑checkout users (`pip install -e apps/mcp-server`) keep their original path.

### Validation

- **`scripts/smoke-packaging.sh`** now pipes a JSON‑RPC `initialize` frame into `context-router mcp` inside the clean‑venv fixture and asserts a valid response with `serverInfo.version` set. This regression guard closes the gap that let v3.3.0 ship with the bundled MCP path broken while source checkouts passed green.

### Why this slipped v3.3.0

`smoke-packaging.sh` proved `context-router index` works on a fresh install but never exercised `context-router mcp`. Every developer machine runs from a source checkout where `context-router-mcp-server` is installed editable, masking the bundled‑wheel failure mode. The pre-release smoke harness is now the first thing users rely on: it exercises the exact install path end-users take.

---

## [3.3.0] — 2026-04-20

First‑run works, MCP streams, agent output. Shipped in response to the external CR vs code‑review‑graph judge (2026‑04‑19) that flagged three shipping‑quality issues eclipsing algorithm gains: fresh installs indexing zero files, default pack burying the right answer in 50k+ tokens, and opaque `<external>` placeholders eating precision. Four parallel lanes (α/β/γ/δ) delivered 8 new v3‑outcome entries.

### Expected impact

- **First‑run index success**: 0 symbols → ≥1 symbol after `pipx install context-router-cli` + `context-router index`.
- **Default pack size on a free‑text query**: ~50k tokens (v3.2) → ≤4000 tokens (v3.3, `--mode review` sane defaults).
- **`<external>` placeholder items in pack output**: up to 1 of 5 top items (v3.2) → 0 (v3.3, resolved or dropped with count surfaced).

### Added

- `context-router doctor` subcommand — diagnoses analyzer entry points, prints per‑analyzer PASS/WARN, exits 1 on any failure. Non‑silent failure audit for `language_*` plugin discovery (lane α, PR #86).
- `pack --format agent` — emits a JSON array of `{path, lines, reason}` for LLM‑agent consumers. Stderr advisory when paired with `--mode handover` because handover is prose‑oriented (lane β, PR #87).
- MCP `notifications/progress` frames on `get_context_pack` when the client passes `progressToken` and the pack crosses a 2000‑token threshold — visible progress for large pack builds in Claude Code (lane γ, PR #85).
- MCP `resources/list` + `resources/read` under `context-router://packs/<uuid>` — prior packs are addressable as MCP resources. Persistence layer: `packages/core/src/core/pack_store.py` keeps the last 20 packs (lane γ, PR #85).
- `docs/guides/modes.md` — 30‑second decision tree, "I am trying to…" table, per‑mode reference, flag‑interaction matrix, common pitfalls (lane δ, PR #88).
- `scripts/smoke-packaging.sh` + `apps/cli/tests/test_packaging_smoke.py` — build CLI wheel, install into clean venv, index tiny fixture, assert symbols written (lane α, PR #86).
- `scripts/mcp_progress_notifications_probe.py` + `scripts/mcp_resources_probe.py` — subprocess‑driven MCP smoke harnesses wired into `smoke‑v3.sh` (lane γ, PR #85).

### Changed

- `apps/cli/pyproject.toml` now declares `[project.entry-points."context_router.language_analyzers"]` for all 7 extension keys (py, java, ts, tsx, js, cs, yaml) pointing at the bundled modules — fresh installs no longer index zero files (lane α, PR #86).
- `PluginLoader.discover()` emits per‑analyzer stderr `WARN` on import failure or missing entry points; a bare `except: pass` that silently swallowed load errors has been replaced with error collection + single‑line stderr summary (lane α, PR #86).
- `pack --mode review` defaults to `--top-k 5 --max-tokens 4000` when both flags are omitted. One‑line stderr advisory `review-mode defaults applied (--top-k 5 --max-tokens 4000)`; suppressed when either flag is set explicitly (lane β, PR #87).
- `token_budget` from `.context-router/config.yaml` is now honored when `--max-tokens` is omitted (was silently ignored in v3.2). Precedence: CLI flag > env var > config.yaml > hard default (8000). Stderr advisory on explicit override (lane β, PR #87).
- `<external>` pack items are resolved to a real path when possible; unresolved entries are dropped with the count exposed on `pack.metadata.external_dropped` — no more opaque placeholder rows (lane β, PR #87).
- `Orchestrator` now carries a `cachetools.TTLCache` (maxsize 100, ttl 300s) keyed on `(repo_id, mode, query_sha, budget, top_k, items_sha)`; `invalidate_cache(reason=…)` emits a stderr note on repo‑id rotation after reindex (lane β, PR #87).
- MCP `initialize` response now advertises `capabilities.progress == true` and `capabilities.resources.listChanged == true`. All `stdout` writes share a `threading.RLock` so notifications cannot interleave with responses mid‑JSON‑RPC frame (lane γ, PR #85).

### Documentation

- Spec: `docs/superpowers/specs/2026-04-19-v3.3.0-design.md` — approved design with DoD blocks for all 8 outcomes (lane δ, PR #88).
- README points the `pack` mode table at the new mode decision guide (lane δ, PR #88).

### Validation

8 of 8 v3.3 outcomes registered in `docs/release/v3-outcomes.yaml` and wired to `scripts/smoke-v3.sh`. All four lane PRs shipped with a ship‑check verdict pasted in the PR body.

### Known follow‑ups

- Homebrew tap PAT scope still blocks the auto‑bump step of the release workflow (carry‑over from v3.2.0). PyPI publish + GitHub Release are unaffected.

---

## [3.2.0] — 2026-04-19

Ten-outcome cycle driven by the external CR vs code-review-graph eval (fastapi, 2026-04-19, `project_context/fastapi/.eval_results/`). Closes four of five scoring dimensions where CR trailed; ends the recurring manual Homebrew tap toll.

### Expected eval delta

- Per-task score (CR vs CRG, same inputs): 23/50 (v0.3 via Homebrew) → 27/50 (v3.1 est.) → **40/50 target (v3.2)**
- Pack item count on fastapi review-mode: 498 (v3.1) → ~50 after `review-tail-cutoff` + `symbol-stub-dedup`
- `reason` field: category labels → function-level symbol + line range

### Added

- `--pre-fix <sha>` on `pack` CLI and `pre_fix` in MCP `get_context_pack` — diff-less review-mode packs for CRG-comparable workflow (P2, PR #80).
- `--top-k N` on `pack` CLI and `top_k` in MCP `get_context_pack` — post-rank cap on `selected_items` (P2, PR #78).
- `--keep-low-signal` escape hatch on `pack` CLI and `keep_low_signal` in MCP `get_context_pack` — preserves the full tail when tail cutoff would prune it (P1, PR #83).
- New `packages/graph-index/src/graph_index/blame.py` — diff line extraction module powering diff-aware boost (PR #82).
- New `eval/fastapi-crg/` reproducible harness — `run.sh`, `score.py`, `extract_files.py`, `fixtures/tasks.yaml`; CR vs CRG scoring on 3 real fastapi commits (P1, PR #73).
- `scripts/render_homebrew_formula.py` — templating for the Homebrew formula, drives the new CI automation (P0, PR #74).
- `docs/release/homebrew-setup.md` — one-time PAT setup guide for the Homebrew tap automation.

### Changed

- Pack `reason` field now includes symbol name and source line range when backed by a symbol (e.g. `Modified OAuth2PasswordRequestForm.__init__ lines 59-159`) — up from generic category labels (P0, PR #75).
- Ranker adds `+0.15` confidence boost (clamped at 0.95) to items whose symbol overlaps the blame trail of changed lines; `pack.metadata.boosted_items` exposes the boosted IDs (P2, PR #82).
- Review-mode pack drops trailing `source_type=file` items with confidence < 0.3 when higher tiers already fill the budget; typical reduction from 498 → ~50 items without losing the ground-truth file (P1, PR #83).
- Multiple pack items with identical `excerpt` + identical title prefix within a single file are collapsed to one representative item; `duplicates_hidden` counter surfaces the collapsed count (P1, PR #77).
- `pack_cache` cache-key now includes `capabilities.hub_boost` so toggling `CAPABILITIES_HUB_BOOST` no longer returns a stale cache (P1, PR #81).
- `pack --mode review` with a free-text query and no diff now prints a stderr warning: "review mode expects a diff; for query-only input, try --mode debug" — silent no-op rule enforcement (P1, PR #76).

### CI / Release

- `.github/workflows/release.yml` now includes a `homebrew-publish` job that automatically bumps the Homebrew tap formula on every `v*` tag push — driven by a one-time-configured `HOMEBREW_TAP_TOKEN` secret (P0, PR #74). No more manual tap updates.

### One-time action required for Homebrew auto-publish

1. Create a fine-grained PAT at https://github.com/settings/personal-access-tokens/new — owner `mohankrishnaalavala`, repo access limited to `homebrew-context-router`, `Contents: Read and write`, 1-year expiry.
2. On the `context-router` repo → Settings → Secrets and variables → Actions → New repository secret `HOMEBREW_TAP_TOKEN` with that PAT.
3. Ensure the tap repo has a `Formula/` directory (empty commit with `Formula/.gitkeep` if missing).

Full instructions: `docs/release/homebrew-setup.md`.

### Validation (ship-check sweep on develop HEAD)

10 of 10 v3.2 outcomes PASS. `function-level-reason` passes via its handler's fastapi-fixture SKIP path (feature itself verified by 124/124 unit-test run during Agent A). All other outcomes PASS with positive assertions on this repo or the local fastapi fixture.

---

## [3.1.0] — 2026-04-18

v3.1 — hotfix cycle after the v3.0.0 post-release audit. 8 PRs (#63–#70)
address the P0/P1/P2 items surfaced by the 7-prompt playbook against the
three fixture repos.

### Fixed (P0 / P1 / P2)

- **Benchmark keyword-baseline vs_keyword honest** — removed the `max(0, …)`
  clamp at `packages/benchmark/src/benchmark/reporters.py` that hid cases
  where the keyword baseline was smaller than the router pack. Negative
  deltas are now surfaced; `vs_keyword` column uses signed formatting.
  Added `vs_keyword`, `vs_naive`, `keyword_baseline_tokens`,
  `naive_baseline_tokens` fields to `TaskMetrics`. (#67, P0)
- **C# `tested_by` / method-name extraction** already landed in v3.0.0 #60;
  v3.1 adds regression tests + a dedicated `edge-source-resolution-fix`
  registry outcome to lock the contract.
- **TypeScript analyzer now emits `tested_by`** on function-component +
  JSX-rendered test patterns (bulletproof-react went from 0 → 45
  `tested_by` edges). New helpers `_TEST_BLOCK_CALLEES`,
  `_TEST_UTILITY_CALLEES`, `_is_test_block_call`,
  `_synthesize_test_name`, `_jsx_tag_identifier`. Class-based path
  unchanged. (#65, P1)
- **Contracts-boost endpoint matching tightened** — `file_references_endpoint`
  now requires a literal path match (modulo parameter segments), with
  HTTP-method-aware preference when the caller hints the method. Stops
  generic verbs like "create order" rewarding unrelated POST consumers. (#68, P1)
- **Minimal-mode ranker preserves top implement-mode result** — new
  `_preserve_top_implement_item` overlay guarantees that for task-verb
  queries, the top implement pick survives the ≤5-item cap. (#64, P1)
- **Hub-bridge smoke query fixed** — root-caused as a pack_cache
  collision (CAPABILITIES_HUB_BOOST was not in the L2 cache key): the
  handler now purges `pack_cache` between OFF and ON runs and reads
  `selected_items` (the authoritative field). The smoke now flips 2
  NamedEntity methods into top-5 deterministically. Product-level
  cache-key gap noted for v3.2. (#66, P2)
- **Flows N+1 eliminated** — `_FlowCache` in `packages/graph-index/src/graph_index/flows.py`
  memoizes `_callees(symbol_id)` per BFS call. 1.73× fewer SQL queries
  on eShopOnWeb (834 → 481). Functional output bit-identical. (#69, P2)
- **Hub-bridge reuses Orchestrator sqlite connection** — `ContextRanker`
  accepts an optional `db_connection` kwarg; Orchestrator threads
  `Database.connection` into it so hub-bridge boost no longer opens
  fresh connections (0 ranker-attributed `sqlite3.connect` calls per
  pack build, down from 2). Standalone ranker fallback path preserved. (#70, P2)

### Changed

- `README.md` Feature Overview: MCP row 16 → 17 tools; add mimeType
  + progress-frame details to the summary.
- `BENCHMARK_RESULTS.md`: v3.0.0 section refreshed with measured
  numbers from the post-release audit (3 fixtures + self); v3.1
  addendum with the honest vs_keyword deltas.
- `docs/release/v3-outcomes-plain-english.md`: "What actually
  happened" section with real measurements.

### New documentation

- `docs/release/v3_1-roadmap.md` — Wave 1 / Wave 2 lane map.
- `internal_docs/v3_review_findings/prompt-{1..7}-*.md` — per-prompt
  audit findings (gitignored).
- `internal_docs/production-readiness-review-v3.md` — aggregated
  review (gitignored).

### Known v3.2 follow-ups (from this cycle)

- **Cache-key must include `capabilities.hub_boost`** so toggling the
  config reliably invalidates cached packs. Workaround for v3.1:
  caller purges `pack_cache` between on/off runs.
- **Homebrew tap repo** still pinned at `0.3.0`; tap update + sha256
  regen is external user action.

---

## [3.0.0] — 2026-04-18

v3.0.0 — CRG-parity, cache persistence, MCP streaming, handover wiki, and
correct graph edges. 25 PRs merged across five phases (scaffolding + four
implementation phases), gated by the new ship-check quality system.

Every feature in this release has a matching entry in
[`docs/release/v3-outcomes.yaml`](docs/release/v3-outcomes.yaml) with a
specific command that proves it works. `scripts/smoke-v3.sh` runs them all.

### Added

- **Phase 1 — first impressions**
  - `context-router --version` prints the installed semver (#38).
  - Pack CLI table dedupes rows by `(title, path_or_ref)` and shows
    "(N duplicate(s) hidden)" (#39).
  - Java/C# interfaces, records, and enums now emit correct `kind`
    values (#40).
  - CI runs on push to `develop`, not just `main` (#36).
- **Phase 2 — speed & discoverability**
  - `--with-semantic` applies in every pack mode (review / debug /
    implement / handover / minimal). The phase-1 stderr warning was
    superseded (#42, #46).
  - Pack cache persists across CLI invocations via a new SQLite L2 tier
    (migration 0012); repeat calls are ≥2× faster (#43).
  - Contracts-consumer boost applies to single-repo packs, not just
    multi-repo workspaces (#44).
  - New `context-router embed` subcommand (migration 0013) pre-computes
    symbol embeddings into a persistent table so `pack --with-semantic`
    is a cosine lookup instead of an on-the-fly compute (#45).
- **Phase 3 — CRG-parity intelligence**
  - New `context-router graph call-chain --symbol-id N` + MCP
    `get_call_chain` tool expose symbol-level call chains (#47).
  - Analyzers emit `extends`, `implements`, and `tested_by` edges for
    Java, C#, Python, and TypeScript (#48). YAML remains edge-free.
  - New `pack --mode minimal` + MCP `get_minimal_context(task)` tool
    return ≤5 items under a tight token budget with a
    `next_tool_suggestion` hint (#49).
  - Java, C#, and TypeScript enums emit `kind='enum'` (#50).
  - New `context-router audit --untested-hotspots` command ranks
    high-inbound-degree symbols with zero `TESTED_BY` edges (#51).
  - Hub and bridge node metrics available as opt-in ranking boost via
    `capabilities.hub_boost` config flag (#52).
  - `pack --mode review` adds a per-item `risk` label
    (none / low / medium / high) based on git diff + file size (#53).
- **Phase 4 — advanced features & MCP polish**
  - Large MCP packs (>2k tokens) emit ≥2 `notifications/progress`
    before the final response (#54).
  - Debug mode annotates items with a `flow` label (entry → leaf along
    `calls` edges) when the graph supports it (#55).
  - Benchmark harness emits 95% confidence intervals for every metric;
    new `benchmark run --runs N` flag, default 10 (#56).
  - MCP `tools/call` content blocks include `mimeType`; `initialize`
    response's `serverInfo.version` reads from `importlib.metadata` (#57).
  - New `pack --mode handover --wiki` generates a markdown wiki of the
    top subsystems (#59).
  - Workspace orchestrator warns on cross-community edge coupling above
    `capabilities.coupling_warn_threshold` (#58, default 50).

### Changed

- `--with-semantic` no longer silently no-ops outside implement mode
  (phase-1 warning replaced by full-mode support in phase 2).
- Pack dedup lives in `Orchestrator.build_pack` so MCP, `explain last-pack`,
  and `pack --json` all return the same deduped pack the CLI table shows
  (#41). `ContextPack` gains a `duplicates_hidden: int` field.
- `ContextItem` model gains `flow: str | None` (#55) and
  `risk: Literal["none", "low", "medium", "high"]` (#53) fields.
- `ContextPack.mode` literal gains `"minimal"` (#49).

### Fixed

- C# analyzer mis-extracted method names (return-type leaks like `Task`,
  `StringContent`, `HttpClient`) as `kind='method'` symbols. Now uses
  `child_by_field_name("name")` and emits only from `method_declaration`
  nodes (#60).
- `extends` / `implements` / `tested_by` edges were anchoring on
  constructor rows that shared the class name. Writer now prefers
  `kind IN ('class', 'record', 'interface', 'enum')` when resolving the
  source symbol (#60).

### New dependencies

- Optional `semantic` extra on `context-router-cli` pulls
  `sentence-transformers` for the embedding cache.

### New configuration keys

- `capabilities.hub_boost` (bool, default false) — opt-in hub/bridge boost.
- `capabilities.contracts_boost` (bool, default true) — single-repo
  contracts-consumer boost.
- `capabilities.coupling_warn_threshold` (int, default 50) — workspace
  cross-community coupling warning threshold.

### New migrations

- `0012_pack_cache.sql` — persistent L2 pack cache (`pack_cache` table).
- `0013_embeddings.sql` — persistent symbol embeddings (`embeddings` table).

### Ship-check quality gate (scaffolding landed 2026-04-17)

- New `docs/release/` — DoD template, 24-outcome registry, plain-English
  outcomes doc, phased roadmap.
- New `scripts/smoke-v3.sh` — executable registry-driven gate; report
  artifacts land in gitignored `internal_docs/ship-check/reports/`.
- New `.claude/skills/ship-check/SKILL.md` + `/ship-check` slash command
  — mandatory for every feature per the `CLAUDE.md` "Feature quality
  gate" section.
- Silent-failure rule: any flag / mode / tool that has no effect in a
  context MUST emit a stderr warning naming the reason.
- Per-phase re-reviews (prompts 1-7 playbook) run at each phase
  completion; reports archived to
  `internal_docs/ship-check/per-phase-reviews/`.

### Known follow-ups (tracked for v3.1)

- Tighten `hub-bridge-ranking-signals` smoke query — current query's
  top-5 is BM25-dominated on spring-petclinic so the +0.10 boost cannot
  flip positions. Unit tests prove the feature works.
- MCP `get_minimal_context` tool published to the MCP directory registry.

---

## [2.0.0] — 2026-04-16

Phase P3 — enhancement ideas. Six P3 items shipped across four independent
work lanes (PRs #29, #30, #31, #32) merged to `main` in a single release cut.

Major version bump reflects new public surface: the MCP server gains a
`resources` capability and progress notifications; the CLI gains
`--with-semantic` and `workspace detect-links`; `Orchestrator.build_pack`
gains three new optional kwargs. Existing callers are unchanged — defaults
are safe.

### Added

- **P3-1 — Orchestrator-level TTLCache for pack results**
  (`packages/core/src/core/orchestrator.py`, `packages/ranking/src/ranking/ranker.py`).
  `Orchestrator.build_pack` now caches the ranked `ContextPack` in a
  `cachetools.TTLCache(maxsize=100, ttl=300)` keyed on
  `(repo_id, mode, sha256(query), budget, use_embeddings, items_hash)`.
  `repo_id` is derived from the SQLite DB mtime so `build_index` /
  `update_index` naturally invalidates entries. An `RLock` guards mutations
  and `invalidate_cache()` is exposed as an escape hatch. The in-ranker
  BM25 corpus cache is preserved — the new cache sits above it and
  short-circuits the entire pipeline on repeat calls.
- **P3-2 — `--with-semantic` CLI flag with rich progress bar**
  (`apps/cli/src/cli/commands/pack.py`, `packages/ranking/src/ranking/ranker.py`).
  `context-router pack --with-semantic` enables `all-MiniLM-L6-v2` semantic
  ranking. First run downloads the model (~33 MB) with a `rich.progress.Progress`
  spinner; the progress bar auto-suppresses when the model is already
  cached. `--no-progress` disables rendering for CI. MCP parity:
  `get_context_pack` input schema gains a matching `use_embeddings` flag
  and always calls `build_pack(progress=False)` so JSON-RPC stdio frames
  are never corrupted.
- **P3-3 — Cross-language contracts extractor** (new package
  `packages/contracts-extractor/`, storage migration `0011_contracts.sql`,
  `ContractRepository`, `WorkspaceDescriptor.contract_links`,
  `workspace detect-links` CLI subcommand). Walks a repo and emits
  signature-level `ApiEndpoint` / `GrpcService` / `GraphqlOperation`
  records. `detect_contract_links(repos)` scans non-producer repos for
  HTTP-client calls matching each endpoint path template and infers
  `ContractLink(kind="consumes")` edges. `workspace_orchestrator` boosts
  items on the producer side of a consumes edge by +0.05.
- **P3-4 (part 1) — Function-level call graph foundation**
  (`packages/storage-sqlite/src/storage_sqlite/repositories.py`, migration
  `0010_edges_repo_type_index.sql`, `contracts.interfaces.SymbolRef`).
  New `EdgeRepository.get_call_chain_symbols(repo, symbol_id, max_depth)`
  returns `SymbolRef` per reachable callee with minimum hop depth. The
  existing `get_call_chain_files` is kept as a back-compat wrapper.
  Migration 0010 adds `idx_edges_repo_type` — fixes a full-table-scan
  hotspot identified in the performance review.
- **P3-5 — MCP progress notifications**
  (`apps/mcp-server/src/mcp_server/main.py`, `tools.py`,
  `Orchestrator.build_pack`). `tools/call get_context_pack` now honours an
  optional `progressToken`. When supplied, `notifications/progress` is
  emitted at three fixed milestones (candidates → ranked → serialized)
  plus per-1,000-token chunk updates for packs larger than 2,000 tokens.
  A new `_notify()` helper writes JSON-RPC notifications to stdout under
  the same mutex as `_send()`.
- **P3-6 — MCP resources capability** (new files `resources.py`,
  `pack_store.py`). The `initialize` response now advertises
  `resources: { listChanged: true }`. `resources/list` and `resources/read`
  expose previously built packs via `context-router://packs/<uuid>`.
  `PackStore` persists to `.context-router/packs/<uuid>.json` + an index
  with LRU retention (last 20 packs). `notifications/resources/list_changed`
  fires after any pack-building tool succeeds.

### Changed

- `Orchestrator.build_pack` gains three new optional kwargs:
  `use_embeddings: bool = False` (P3-2), `progress: bool = True`
  (transport safety toggle), `download_progress_cb: Callable[[str], None]`
  (rich spinner for model download), and `progress_cb: Callable[[str, int, int], None]`
  (pack-build progress for MCP). All default to safe values; existing
  callers require no changes.
- `WorkspaceDescriptor` gains a `contract_links: list[ContractLink]` field.
  The legacy `links: dict[str, list[str]]` shape is unchanged and
  existing `workspace.yaml` files round-trip as before.
- MCP `get_context_pack` input schema adds `use_embeddings` (boolean) and
  `progressToken` (string | integer) — both optional and additive.

### New dependencies

- `cachetools>=5.3` (core, cli) — bounded TTL cache for pack results.
- `rich>=13.0` (cli) — progress spinner for model download.

### Deferred follow-ups

- **P3-4 part 2** — entrypoint registry, reachability analysis, dead-code
  detection, `context-router audit --dead-code` CLI. The storage foundation
  lands here; the analytical layer is a follow-up PR.
- **ADR** — "Contract extraction scope = signatures only" was planned but
  not filed with this release. Rationale is referenced in the Lane D PR
  body and will be written up into `.handover/context/decisions.md`.

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
