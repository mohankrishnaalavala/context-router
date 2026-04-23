# context-router

[![PyPI](https://img.shields.io/pypi/v/context-router-cli)](https://pypi.org/project/context-router-cli/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io)
[![Tests](https://github.com/mohankrishnaalavala/context-router/actions/workflows/ci.yml/badge.svg)](https://github.com/mohankrishnaalavala/context-router/actions)

A local-first CLI and MCP server that selects the **minimum useful context** across code structure, runtime evidence, and project memory for AI coding agents — reducing token consumption on review, debug, implement, and handover tasks.

## Why

AI coding agents work best with focused, relevant context rather than entire codebases. context-router:

- Indexes your repo's symbols, dependency edges, call graphs, and test coverage into a local SQLite database
- Ranks candidates by structural relevance, query similarity, and community membership for your task mode
- Enforces a configurable token budget so your agent prompt stays lean (50–88% token reduction depending on codebase size and language)
- Explains every selection decision in one human-readable sentence
- Supports multi-repo workspaces with cross-repo confidence boosting
- Works as a CLI, MCP server, or Python library — no API key required

## Feature Overview

| Feature | Detail |
|---|---|
| **Language support** | Python (full), TypeScript/JS (full), YAML (k8s/Helm/GHA), Java (full with `enum`), .NET/C# (full with `record` / `enum`) |
| **Edge types** | `imports`, `calls` (symbol-level), `extends`, `implements`, `tested_by`, `needs` (GHA), community links |
| **Task modes** | `review` (adds per-item `risk` from git diff + size), `implement`, `debug` (annotates items with flow: entry → leaf), `handover` (with `--wiki` for a markdown subsystem summary), `minimal` (≤5 items under tight token budget with `next_tool_suggestion`) |
| **Ranking** | BM25 query scoring (Okapi BM25, inline, no extra dependency), freshness decay (30-day half-life), optional `--with-semantic` semantic boost (all-MiniLM-L6-v2, applies in every pack mode), community-cohesion boost (+0.10 for same-cluster candidates), opt-in hub/bridge structural boost via `capabilities.hub_boost`, single-repo contracts-consumer boost (+0.10 when an item's file references a same-repo OpenAPI endpoint), per-project `confidence_weights` overrides in `.context-router/config.yaml` |
| **Pack cache** | Two-tier cache: in-process L1 (5-minute TTLCache) + SQLite L2 (survives across CLI invocations) — keyed on `(repo_id, mode, sha256(query), budget, use_embeddings, items_hash)`; `repo_id` derived from `(COUNT(*), MAX(id))` of `symbols` so writes to `pack_cache` don't self-invalidate |
| **Embeddings** | Proactive cache via `context-router embed` — pre-computes symbol embeddings once (stored in `embeddings` table), then `pack --with-semantic` is a cosine lookup instead of on-the-fly encoding; on-the-fly fallback with stderr warning when the table is empty |
| **Audit** | `context-router audit --untested-hotspots` ranks high-inbound symbols with zero `tested_by` edges (requires `tested_by` edges from recent indexing) |
| **Version & discovery** | `context-router --version` prints installed semver; MCP `serverInfo.version` reads from `importlib.metadata`; every MCP `tools/call` content block carries a `mimeType` |
| **Token budget** | Value-per-token knapsack admission + hard cap with per-source-type guarantee; dynamic scaling for small repos |
| **Memory** | Persistent observations (FTS), ADRs, freshness scoring, `memory export`, `decisions export` |
| **Feedback loop** | `feedback record/stats/list` — per-file confidence adjustments; `--files-read` tracks actual file consumption for read-coverage analytics |
| **Debug memory** | `error_hash` deduplication, `top_frames` extraction, `past_debug` recall (same error = boosts prior fix files) |
| **Multi-repo** | Workspace YAML, cross-repo link detection from Python imports **and** real OpenAPI/protobuf/GraphQL signatures via `workspace detect-links`, unified ranked pack with contract-edge boost |
| **Graph viz** | Interactive D3.js HTML — color by kind or community cluster |
| **Call flow analysis** | Symbol-level `EdgeRepository.get_call_chain_symbols` (BFS with per-hop depth); debug mode walks `calls` edges up to 3 hops and surfaces `call_chain` items with decaying confidence (0.45 → 0.315 → 0.22) |
| **MCP server** | **17 tools** over stdio JSON-RPC 2.0 with validated `inputSchema.required` and `outputSchema` on every tool; `resources` capability for addressable pack history (`context-router://packs/<uuid>`); `notifications/progress` for large packs (≥2 frames on >2k-token responses, 0 on small); every content block carries `mimeType`; compatible with Claude Code, Cursor, Windsurf |
| **Agent adapters** | Claude system prompt, Copilot instructions, Codex task prompt |
| **Benchmarks** | Generic 20-task suite plus language-specific suites (React, Spring Boot, ASP.NET Core — `--task-suite` flag), 3 baselines, external repo testing, JSON + Markdown report with 95% CIs per metric (`--runs N`, N≥10 → non-null `ci95`; below 10 emits `ci95: null` plus a stderr warning) |

## Requirements

- Python 3.12+

## Install

**Homebrew (macOS/Linux):**
```bash
brew tap mohankrishnaalavala/context-router
brew install context-router
```

**uv (recommended — auto-manages Python):**
```bash
uv tool install context-router-cli
```

**pip / pipx:**
```bash
pip install context-router-cli
# or
pipx install context-router-cli
```

**From source:**
```bash
git clone https://github.com/mohankrishnaalavala/context-router
cd context-router
uv sync --all-packages
```

> [context-router-cli on PyPI](https://pypi.org/project/context-router-cli/)

---

## Quickstart

```bash
# 1. Initialize a project (creates .context-router/ with config + SQLite DB)
context-router init

# 2. Configure your AI coding agent (Claude Code, Copilot, Cursor, Windsurf, or Codex)
#    Auto-detects which agent you use from existing config files
context-router setup
#    Or target a specific agent:
context-router setup --agent claude   # also registers the MCP server in .mcp.json
context-router setup --agent all      # configure every agent at once

# 3. Index the repository — extracts symbols, call edges, test links, communities
context-router index

# 3. Generate a context pack for a code review
uv run context-router pack --mode review

# 4. Implement a feature — query-aware ranking surfaces the right files
uv run context-router pack --mode implement --query "add pagination to the users endpoint"

# 5. Debug a failure — parse an error file and rank by blast radius
uv run context-router pack --mode debug --error-file pytest-output.xml

# 5b. Fast triage — minimal mode returns ≤5 items under a tight 800-token
#     budget plus a `metadata.next_tool_suggestion` hint for follow-up
uv run context-router pack --mode minimal --query "review the ranker" --max-tokens 800 --json

# 6. Explain what was selected and why
uv run context-router explain last-pack

# 7. Visualize the symbol graph
uv run context-router graph --open

# 8. Get machine-readable JSON for scripts or agent prompts
uv run context-router pack --mode review --json
```

---

## Commands Reference

| Command | Purpose |
|---|---|
| [`init`](#init) | Initialize `.context-router/` config and database |
| [`setup`](#setup) | Configure AI coding agents (Claude Code, Copilot, Cursor, Windsurf, Codex) |
| [`index`](#index) | Scan and index all source files |
| [`watch`](#watch) | Incrementally re-index on file save |
| [`pack`](#pack) | Generate a ranked context pack |
| [`explain`](#explain) | Explain the last pack's selections |
| [`memory`](#memory) | Add/search/export session observations |
| [`decisions`](#decisions) | Add/search/export architectural decision records |
| [`feedback`](#feedback) | Record and review agent feedback for context packs |
| [`graph`](#graph) | Generate interactive HTML graph visualization |
| [`workspace`](#workspace) | Multi-repo workspace management |
| [`benchmark`](#benchmark) | Run 20-task benchmark suite |
| [`mcp`](#mcp) | Start the MCP server (for Claude Code, Cursor, Windsurf) |

---

### `init`

Initialize a project. Creates `.context-router/config.yaml` and `.context-router/context-router.db`.

```
context-router init [--project-root PATH] [--json]
```

---

### `setup`

Configure AI coding agents to use context-router. Appends context-router instructions to the
appropriate config files and registers the MCP server in `.mcp.json`.

```
context-router setup [--agent AGENT] [--project-root PATH] [--dry-run]
```

**Supported agents:** `claude`, `copilot`, `cursor`, `windsurf`, `codex`, `all`

| Agent | Files written/updated |
|-------|-----------------------|
| `claude` | `CLAUDE.md` + `.mcp.json` (MCP server entry) |
| `copilot` | `.github/copilot-instructions.md` |
| `cursor` | `.cursorrules` |
| `windsurf` | `.windsurfrules` |
| `codex` | `AGENTS.md` |

When `--agent` is omitted, auto-detects from existing config files. Use `--dry-run` to preview
changes without writing anything. Idempotent — safe to re-run.

```bash
# Auto-detect and configure
context-router setup

# Configure for Claude Code (also adds MCP server to .mcp.json)
context-router setup --agent claude

# Configure all agents at once
context-router setup --agent all

# Preview what would change
context-router setup --agent all --dry-run
```

---

### `index`

Scan and index the repository.

```
context-router index [--project-root PATH] [--repo REPO_NAME]
```

Walks all source files, runs language analyzers (discovered via `context_router.language_analyzers` entry points), and writes to the local DB:

- **Symbols** — functions, classes, interfaces, k8s resources, GitHub Actions jobs
- **Import edges** — which files import which modules
- **Call edges** — which functions call which functions (Python, TypeScript)
- **TESTED_BY edges** — links `test_foo` → `foo` by name convention
- **Community IDs** — Union-Find clustering of connected symbols

```bash
uv run context-router index
# Indexed 286 files — 1765 symbols, 3174 edges (2.82s)
```

---

### `watch`

Watch for file changes and incrementally re-index.

```
context-router watch [--project-root PATH]
```

---

### `pack`

Generate a ranked context pack for a task.

```
context-router pack --mode MODE [--query TEXT] [--project-root PATH] [--json]
```

**Modes:**

| Mode | Ranking priority | Best for |
|---|---|---|
| `review` | changed files → blast radius → impacted tests → config | PR review, diff analysis |
| `implement` | entrypoints → contracts → extension points → patterns | Building new features |
| `debug` | runtime signal match → failing tests → changed files → call chain | Fixing errors, CI failures |
| `handover` | recent changes → memory observations → decisions → blast radius | Onboarding, sprint docs |
| `minimal` | implement-mode ranking, hard-capped to the top 5 items | Cheap triage; pairs with a `metadata.next_tool_suggestion` hint for the next call |

Not sure which mode to pick? See the full **[mode decision guide](docs/guides/modes.md)** — one paragraph per mode plus an "I am trying to… → mode" table.

**Token budget** (default: 8 000 tokens) is read from `.context-router/config.yaml`. Items are dropped lowest-confidence first, but at least one item per source category is always preserved. `--max-tokens N` overrides the budget for a single call (minimal mode defaults to 800 when the flag is omitted).

The pack is saved to `.context-router/last-pack.json` for later inspection.

**Handover wiki mode.** `context-router pack --mode handover --wiki` skips the ranker entirely and emits a deterministic markdown "subsystem wiki" built from the indexed graph: the top communities are ranked by total inbound hub degree, and each section lists the key files, hub symbols, and a template-based one-paragraph summary. Stream to stdout by default or write to a file with `--out PATH`. The `--wiki` flag is handover-only — combining it with any other `--mode` is a usage error.

**Examples:**

```bash
# Review mode — surfaces changed files and their dependencies
uv run context-router pack --mode review

# Implement with query — boosts items matching "rate limiting"
uv run context-router pack --mode implement --query "add rate limiting to API endpoints"

# Debug with error file — parse pytest/JUnit XML to find root cause
uv run context-router pack --mode debug --error-file test-results.xml

# JSON output for piping into agent prompts
uv run context-router pack --mode review --json | jq '.selected_items[].title'
```

---

### `explain`

Explain the last generated context pack.

```
context-router explain last-pack [--show-call-chains] [--json]
```

```
  [changed_file]  build_pack (orchestrator.py)       — Modified in current diff
  [blast_radius]  ContextRanker (ranker.py)           — Depends on a changed file
  [impacted_test] test_ranker.py                      — Tests code affected by this change
  [contract]      ContextItem (models.py)             — Data contract or interface definition
```

`--show-call-chains` groups `call_chain` items under a labelled section, making it easy to distinguish inferred call-chain candidates from structural ones.

---

### `memory`

Persist and search session observations. Stored in the local SQLite DB with FTS5 full-text search.

```
context-router memory add --from-session SESSION.json   # import from JSON file
context-router memory add --stdin                        # import from stdin pipe
context-router memory capture SUMMARY [OPTIONS]          # capture inline from args
context-router memory search QUERY
context-router memory list [--sort freshness|recency|confidence] [--limit N]
context-router memory stale
context-router memory export [--output PATH] [--redacted] [--limit N]
```

`stale` lists observations whose referenced files no longer exist in the index.

`capture` applies guardrails automatically: duplicates (same task type + summary) are silently
skipped, and secret values in `--commands` are redacted before storage.

`export` writes a single Markdown file suitable for team sharing. Pass `--redacted` to strip
file paths and commit SHAs (keeps fix summaries).

**Freshness scoring**: `effective_confidence = min(0.95, confidence × decay + access_boost)`.
Decay uses a 30-day half-life; each search access adds +0.02 (capped at +0.20). Stale
observations fade gracefully rather than being deleted.

**Examples:**

```bash
# Capture an observation inline — no JSON file needed
uv run context-router memory capture "fixed auth token expiry bug" \
  --task-type debug \
  --files "auth.py tests/test_auth.py" \
  --commit abc1234 \
  --fix "added 60-second clock-skew tolerance"

# Pipe JSON from another tool
echo '{"summary": "deployed to staging", "task_type": "deploy"}' \
  | uv run context-router memory add --stdin

# Search for past observations about authentication
uv run context-router memory search "auth token"

# List observations sorted by freshness
uv run context-router memory list --sort freshness --limit 20

# Export for team sharing (redacted: strips file paths)
uv run context-router memory export --output docs/memory.md --redacted

# Find observations referencing files that were deleted
uv run context-router memory stale
```

---

### `decisions`

Manage architectural decision records (ADRs). Persisted with FTS5 search across title, context, and decision fields.

```
context-router decisions add TITLE [--decision TEXT] [--context TEXT] [--consequences TEXT] [--tags TAGS] [--status STATUS]
context-router decisions search QUERY
context-router decisions list
context-router decisions supersede OLD_ID NEW_ID
context-router decisions export [--output-dir PATH] [--status accepted|all]
```

`--status` accepts: `proposed` | `accepted` | `deprecated` | `superseded`

`supersede` links an old decision to its replacement, preserving the audit trail.

`export` writes one ADR Markdown file per decision to `output_dir`, named `0001-title-slug.md`.

**Examples:**

```bash
# Record a new ADR
uv run context-router decisions add "Use SQLite for local storage" \
  --decision "SQLite + FTS5 chosen over PostgreSQL" \
  --context "Need offline-capable storage" \
  --status accepted

# Search decisions by keyword
uv run context-router decisions search "database"

# Supersede an old decision with a new one
uv run context-router decisions supersede OLD_UUID NEW_UUID

# Export accepted decisions as individual ADR files
uv run context-router decisions export --output-dir docs/adr/
```

---

### `feedback`

Record agent feedback for context packs — drives confidence adjustments over time.

```
context-router feedback record --pack-id ID [--useful yes|no] [--missing FILES] [--noisy FILES] [--files-read FILES] [--reason TEXT]
context-router feedback stats [--project-root PATH]
context-router feedback list [--limit N] [--project-root PATH]
```

**How it works:**

Each `feedback record` call stores one `PackFeedback` entry. After ≥3 reports for the same file:
- **missing** files get a **+0.05** confidence boost in future packs
- **noisy** files get a **−0.10** confidence penalty in future packs

`--files-read` records which files the agent actually consumed from the pack (space-separated). After ≥5 reports with `files_read`, `stats` shows `read_overlap_pct` (fraction of reads that were pack hits) and `noise_ratio_pct` (fraction of pack items never read).

`stats` shows aggregate usefulness percentage plus top missing and noisy files.

**Examples:**

```bash
# Record that a pack was useful but missed an important file
uv run context-router feedback record \
  --pack-id "$(cat .context-router/last-pack.json | jq -r .id)" \
  --useful yes \
  --missing "auth/middleware.py"

# Record that browser extension files were irrelevant noise
uv run context-router feedback record \
  --pack-id pack-456 \
  --useful no \
  --noisy "dist/extension/background.js" \
  --reason "Browser extension files not relevant for backend debugging"

# View aggregate feedback stats
uv run context-router feedback stats
```

---

### `graph`

Generate a self-contained interactive HTML graph visualization of the indexed symbol graph.

```
context-router graph [--project-root PATH] [--output PATH] [--open] [--json]
```

- Nodes are **colored by kind** (function=green, class=blue, interface=teal, k8s=orange) or by **community cluster** (toggle in the UI)
- Node **size** reflects degree (more connections = larger)
- **Click** any node for a details panel (file, kind, community, signature)
- **Search/filter** by symbol name
- **Zoom/pan** with scroll and drag
- `--open` launches your default browser immediately

```bash
# Generate and open in browser
uv run context-router graph --open

# Save to a path for sharing or docs
uv run context-router graph --output ./docs/graph.html

# Raw JSON for programmatic use
uv run context-router graph --json

# Walk the `calls` edges from a seed symbol and list downstream symbols
uv run context-router graph call-chain --symbol-id 42 --max-depth 3 --json
```

Use `graph call-chain --symbol-id N [--max-depth 3] [--json]` to BFS the
`calls` edges from a seed and emit the downstream symbols (id, name, kind,
file, language, line numbers, hop depth). Same underlying storage method
that `get_call_chain` exposes via MCP.

---

### `workspace`

Manage multi-repo workspaces with cross-repo context packs.

```
context-router workspace init [--root PATH] [--name NAME]
context-router workspace repo add NAME PATH [--root PATH]
context-router workspace repo list [--root PATH] [--json]
context-router workspace link add FROM TO [--root PATH]
context-router workspace pack --mode MODE [--query TEXT] [--root PATH] [--json]
```

**How it works:**

1. `workspace init` creates `workspace.yaml` at the root
2. `repo add` registers each repo and captures its git branch/SHA
3. `link add` declares a dependency between repos (boosts cross-repo confidence)
4. `pack` runs `Orchestrator` per repo, merges candidates labelled with `[repo-name]`, and re-ranks within a unified token budget

```bash
# Set up a two-repo workspace
uv run context-router workspace init
uv run context-router workspace repo add api ./services/api
uv run context-router workspace repo add frontend ./services/frontend
uv run context-router workspace link add frontend api
uv run context-router workspace pack --mode review
```

---

### `benchmark`

Run the built-in 20-task suite and measure token reduction vs naive/keyword baselines.

```
context-router benchmark run [--project-root PATH] [--output PATH] [--json] [--runs N]
context-router benchmark report [--project-root PATH] [--input PATH] [--json]
```

`--runs N` (default **10**) controls how many times each task is executed; 95% confidence intervals are published in the JSON output at `metrics[].ci95` when `N >= 10`. At `N < 10` the CLI prints a stderr warning (`warning: benchmark ran with n=<N> runs; ci95 is null …`) and every `ci95` field is `null` — honest nulls beat noisy intervals.

See [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) for real numbers on external codebases (**49–90% average token reduction**, quality metrics, and per-mode breakdown). Token reduction is highest on large repos (project_handover: 79%, eShopOnWeb: 90%, context-router self on v3.3.1: **99%** at a 10.5k-symbol baseline). Hit-rate benchmarks use a Python-optimized task suite; accuracy on non-Python repos improves with language-specific task suites. External-repo numbers predate v3.2 ranking work and were not re-run for v3.3.1 (MCP hotfix only); scheduled for v4.0 re-measurement.

---

### `mcp`

Start the context-router MCP server over stdio JSON-RPC 2.0, exposing all tools to any MCP-compatible AI coding agent.

```
context-router mcp
```

**Available MCP tools (17 total):**

In v3.0, the server declares a `resources` capability — previously built packs are addressable as `context-router://packs/<uuid>` via `resources/list` and `resources/read`. `tools/call get_context_pack` accepts an optional `progressToken`; large packs (>2k tokens) emit `notifications/progress` milestones (≥2 before the final response). Every content block carries a `mimeType`; `initialize.serverInfo.version` reads from installed package metadata.

| Tool | What it does |
|---|---|
| `build_index` | Full re-index of the repository |
| `update_index` | Incremental re-index for changed files |
| `get_context_pack` | Ranked pack for review / implement / debug / handover / minimal |
| `get_context_summary` | Compact summary of the last pack |
| `get_minimal_context` | Token-cheap triage tool — ≤5 items under a tight budget, returns `next_tool_suggestion` hint |
| `get_debug_pack` | Debug pack with optional error-file (pytest/JUnit XML) parsing; items annotated with flow when available |
| `explain_selection` | Why each item was selected + token count stats |
| `generate_handover` | Handover pack combining changes + memory + decisions |
| `search_memory` | Full-text search of session observations |
| `get_decisions` | Search or list architectural decision records |
| `save_observation` | Persist a coding-session observation (dedup + secret redaction applied) |
| `save_decision` | Persist an architectural decision record (ADR) |
| `list_memory` | List observations sorted by freshness score |
| `mark_decision_superseded` | Link an old decision to its replacement |
| `record_feedback` | Record agent feedback for a context pack (useful/missing/noisy) |
| `get_call_chain` | Walk `calls` edges from a seed symbol id and return downstream symbols (id, name, kind, file, language, line_start) |
| `suggest_next_files` | Suggest likely-next files based on graph adjacency |

---

## MCP Setup Guide

### Claude Code

Add to `.mcp.json` in your project root (or `~/.claude/mcp.json` for global config):

```json
{
  "mcpServers": {
    "context-router": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/your/project", "context-router", "mcp"]
    }
  }
}
```

Then in Claude Code:
```
/mcp
```
You'll see `context-router` listed. Use it with:
```
Use context-router to get a context pack for reviewing my recent changes
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "context-router": {
      "command": "uv",
      "args": ["run", "context-router", "mcp"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

Restart Cursor. The tools appear in the Cursor agent panel under MCP.

### Windsurf

Add to `.windsurf/mcp_config.json`:

```json
{
  "servers": {
    "context-router": {
      "command": "uv run context-router mcp",
      "transport": "stdio"
    }
  }
}
```

### Using MCP Tools in Practice

Once connected, your agent can call tools directly:

```
# Get context for a code review (agent calls get_context_pack)
"Review the auth changes in my PR. Use context-router to find all affected code."

# Debug a failing test (agent calls get_debug_pack)
"My tests are failing with AttributeError. Use context-router to find the root cause."

# Handover documentation (agent calls generate_handover)
"Generate a handover document for what I worked on this sprint."

# Search past decisions (agent calls get_decisions)
"What architectural decisions were made about the database layer?"
```

### Programmatic Use (Python SDK)

```python
from core.orchestrator import Orchestrator

# Get a context pack
pack = Orchestrator(project_root="/path/to/repo").build_pack(
    mode="implement",
    query="add rate limiting to the API"
)

print(f"Selected {len(pack.selected_items)} items, {pack.total_tokens} tokens")
for item in pack.selected_items:
    print(f"  [{item.source_type}] {item.title} — {item.reason}")
```

```python
# With semantic ranking (requires: pip install sentence-transformers)
from ranking.ranker import ContextRanker

ranker = ContextRanker(token_budget=8000, use_embeddings=True)
```

```python
# Agent adapters
from adapters_claude import ClaudeAdapter
from adapters_copilot import CopilotAdapter

pack = Orchestrator().build_pack("review", "fix the auth bug")
print(ClaudeAdapter().generate(pack))    # System prompt preamble for Claude
print(CopilotAdapter().generate(pack))  # .github/copilot-instructions.md
```

---

## Configuration

Edit `.context-router/config.yaml`:

```yaml
# Maximum tokens for a generated context pack (default: 8000)
token_budget: 8000

# Repository name (used as the key in the SQLite DB)
repo_name: default

capabilities:
  # Enable LLM-powered summarization (requires API key — future feature)
  llm_summarization: false

# fnmatch patterns to exclude from indexing
ignore_patterns:
  - ".git"
  - "__pycache__"
  - "*.pyc"
  - "*.egg-info"
  - ".venv"
  - "node_modules"
  - "dist"
  - "build"
```

### Tuning confidence weights (advanced)

Per-mode confidence for each source category can be overridden without
patching the code. Add a `confidence_weights` block to `.context-router/config.yaml`:

```yaml
confidence_weights:
  review:
    changed_file: 0.98   # trust diff-touched files more
    blast_radius: 0.65
  implement:
    entrypoint: 0.95
    file_function: 0.35
  debug:
    failing_test: 0.90
  handover:
    memory: 0.85
```

Missing keys fall back to the built-in defaults, so partial overrides are safe.
Valid source-category keys per mode:

| Mode | Source categories |
|------|-------------------|
| `review`   | `changed_file`, `blast_radius`, `impacted_test`, `config`, `file` |
| `implement` | `entrypoint`, `contract`, `extension_point`, `file_class`, `file_function`, `file` |
| `debug`    | `runtime_signal`, `past_debug`, `failing_test`, `changed_file`, `blast_radius`, `file` |
| `handover` | `changed_file`, `memory`, `decision`, `blast_radius`, `file` |

---

## Architecture

context-router is a `uv` workspace of focused packages with strict import boundaries:

```
packages/
  contracts/            # Pydantic models + plugin protocols (no internal deps)
  storage-sqlite/       # SQLite DB, migrations, FTS5, repositories
  graph-index/          # File scanner, language dispatch, git diff, community detection
  ranking/              # Token estimator, ContextRanker, query/semantic boost
  core/                 # Orchestrator — wires storage + graph + ranking
  language-python/      # Python AST (tree-sitter): symbols, imports, calls
  language-typescript/  # TypeScript/JS AST (tree-sitter): symbols, imports, calls
  language-yaml/        # YAML: k8s resources, Helm charts, GitHub Actions
  language-java/        # Java (full): imports→DependencyEdge, call edges, JavaDoc
  language-dotnet/      # .NET/C# (full): using→DependencyEdge, call edges, attributes
  memory/               # Observation store + FTS + freshness scoring + export
  runtime/              # Stack trace + JUnit/pytest XML parsers + error_hash + top_frames
  workspace/            # Multi-repo workspace support
  benchmark/            # 20-task benchmark harness
  adapters-claude/      # Claude system-prompt adapter
  adapters-copilot/     # GitHub Copilot instructions adapter
  adapters-codex/       # Codex task prompt adapter
apps/
  cli/                  # Typer CLI (all commands)
  mcp-server/           # MCP server entry point
```

**Module boundary rules** (enforced in CI):

- `contracts` has zero internal dependencies
- Only `storage-sqlite` touches SQLite
- Only `core` imports from `storage-sqlite`, `graph-index`, and `ranking`
- CLI and MCP server only import from `core` and `benchmark`

---

## Development

```bash
# Install all packages + dev dependencies
uv sync --all-packages --extra dev

# Run all 544 tests
uv run pytest --tb=short -q

# Lint
uv run ruff check .

# Install git pre-push hook (runs tests before every push)
git config core.hooksPath .githooks

# Re-index after code changes
uv run context-router index

# Check release readiness
/release-check
```

---

## Adding a Language Analyzer

Implement the `LanguageAnalyzer` protocol and register via entry points:

```python
# my_package/analyzer.py
from pathlib import Path
from contracts.interfaces import Symbol, DependencyEdge

class RustAnalyzer:
    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        ...
```

```toml
# pyproject.toml
[project.entry-points."context_router.language_analyzers"]
rs = "my_package.analyzer:RustAnalyzer"
```

Install your package into the workspace and `context-router index` will pick it up automatically.

---

## Benchmark Results

Self-repo numbers were refreshed against v3.3.1 on 2026-04-23. External-repo numbers predate v3.2 ranking work and were not re-run for v3.3.1 (MCP hotfix only); scheduled for v4.0 re-measurement.

### v3.3.1 — self-repo (2026-04-23)

| Codebase | Files | Symbols | Avg reduction (CI) | Hit rate vs random | Latency |
|---|---|---|---|---|---|
| context-router (self) | 1,009 | 10,569 | **99.2%** (99.1–99.2) | **51.1% vs 33.3%** | 407 ms |

20 / 20 tasks succeeded at 10 runs per task. The higher reduction vs prior runs is driven by a larger naive baseline (monorepo + vendored packages) rather than a behavioural regression; absolute pack size remains near the 8,000-token budget. See [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) for detail.

### v0.6 / historical — external Python codebases (not re-run for v3.3.1)

| Codebase | Symbols | Avg reduction | Hit rate vs random | Latency |
|---|---|---|---|---|
| secret-scan-360 (security scanner) | 543 | **49.4%** | **48.1% vs 35.2%** | 105 ms |
| project_handover (Python CLI) | 1,313 | **79.1%** | — | ~750 ms |

_External-repo numbers predate v3.2 ranking work; not re-run for v3.3.1 (MCP hotfix only). Scheduled for v4.0 re-measurement._

**Hit rate** measures whether the right symbols were selected, not just token count. The router outperforms random sampling by +12.9 pp on domain-matched repos (on Python repositories with domain-matched queries).

See [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) for the full per-task breakdown, metric definitions, and confidence scoring explanation.

---

## Roadmap

| Phase | Status | What shipped |
|-------|--------|--------------|
| **Phase 1** — Core foundation | ✅ complete | CLI, SQLite, Python/TS analyzers, 4 pack modes, MCP server (10 tools), benchmark harness |
| **Phase 2** — Memory freshness | ✅ complete | Time-decay scoring (30-day half-life), access boost, `memory list`, `decisions supersede`, `list_memory`/`mark_decision_superseded` MCP tools (12 total) |
| **Phase 3** — Richer language edges | ✅ complete | Java/C# full analyzers (imports + call edges), YAML Docker Compose + GHA `needs` edges, real line numbers |
| **Phase 4** — Better debug memory | ✅ complete | `error_hash` for cross-session error dedup, `top_frames` extraction, `past_debug` confidence tier (0.90), JUnit `failing_tests` |
| **Phase 5** — Team-safe export | ✅ complete | `memory export` (Markdown, redacted mode), `decisions export` (per-ADR .md files with slug filenames) |
| **Phase 6** — Agent feedback loop | ✅ complete | `PackFeedback` model, `pack_feedback` DB table, `feedback record/stats/list` CLI, `record_feedback` MCP tool (13 total), per-file confidence adjustments |
| **Phase 7** — Distribution + DX | ✅ complete | `setup` command (auto-configure Claude/Copilot/Cursor/Windsurf/Codex), Homebrew tap, tiktoken estimation, quality benchmark metrics, additive query boost |
| **Phase P1** — Production quality (v0.6) | ✅ complete | MCP protocol compliance (JSON-RPC errors), `suggest_next_files` 15th tool, multi-run benchmarks w/ CIs, feedback-loop file boost, BM25 memory search, CONTRIBUTING.md |
| **Phase P2** — Ranking and coverage (v0.7) | ✅ complete | Community-cohesion boost, value-per-token knapsack budget, `.context-router/config.yaml` `confidence_weights`, Java/C# constructor extraction, broad Java annotation surface, TypeScript enums + decorators, per-language benchmark suites (`--task-suite`), MCP `required`/`outputSchema` on all 15 tools, indexed `get_adjacent_files` UNION rewrite |
| **Phase P3** — Enhancement ideas (v2.0) | ✅ complete | Orchestrator-level TTLCache for pack results, `--with-semantic` CLI opt-in with rich progress bar, cross-language contracts extractor (OpenAPI/protobuf/GraphQL) + `workspace detect-links` + `consumes` contract edges, symbol-level call-chain query + `edges(repo, edge_type)` index, MCP progress notifications for large packs, MCP `resources` capability with URI-addressable pack history |
| **Phase v3** — CRG-parity, cache persistence, MCP streaming, wiki, edges (v3.0) | ✅ complete | 25 PRs (#36–#60), gated by the new ship-check quality system. `--version` + pack dedup + interface/record/enum kinds + CI on develop + `--with-semantic` in every mode + SQLite L2 pack cache (persists across CLI runs) + single-repo contracts boost + `context-router embed` subcommand + `get_call_chain` MCP tool + `extends`/`implements`/`tested_by` edges + `--mode minimal` + `audit --untested-hotspots` + opt-in hub/bridge boost + review-mode risk column + streaming large packs + flow-level debug + 95% CI benchmarks + MCP mimeType/version + handover `--wiki` + cross-community coupling warning + C# analyzer accuracy fixes. See [`CHANGELOG.md`](CHANGELOG.md) and [`docs/release/v3-outcomes.yaml`](docs/release/v3-outcomes.yaml). |
| **Phase 8** — Astro/Vue/Svelte | planned | Single-file component analyzers for modern frontend repos |
| **Phase v3.1** — Follow-ups | planned | Tighten hub/bridge smoke query on BM25-dense fixtures; MCP directory-registry submission for `get_minimal_context`; entrypoint-based dead-code audit on top of v3's symbol-level call-chain |

---

## Contributing

See `.handover/` for architecture context, decision records, and open tasks.

- Architecture: `.handover/context/architecture.md`
- Decision log: `.handover/context/decisions.md`
- Task list: `.handover/work/tasks.md`
- Coding standards: `.handover/standards/coding-standards.md`

---

## License

MIT — see [LICENSE](LICENSE).
