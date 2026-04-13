# context-router

A local-first CLI and MCP server that selects the **minimum useful context** across code structure, runtime evidence, and project memory for AI coding agents — reducing token consumption on review, debug, implement, and handover tasks.

## Why

AI coding agents work best with focused, relevant context rather than entire codebases. context-router:

- Indexes your repo's symbols, dependency edges, call graphs, and test coverage into a local SQLite database
- Ranks candidates by structural relevance, query similarity, and community membership for your task mode
- Enforces a configurable token budget so your agent prompt stays lean (64.7% average reduction)
- Explains every selection decision in one human-readable sentence
- Supports multi-repo workspaces with cross-repo confidence boosting
- Works as a CLI, MCP server, or Python library — no API key required

## Feature Overview

| Feature | Detail |
|---|---|
| **Language support** | Python (full), TypeScript/JS (full), YAML (k8s/Helm/GHA), Java, .NET (stubs) |
| **Edge types** | `imports`, `calls` (function-level), `tested_by`, community links |
| **Task modes** | `review`, `implement`, `debug`, `handover` |
| **Ranking** | Confidence scoring, query keyword boost, optional semantic boost (sentence-transformers) |
| **Token budget** | Hard cap with per-source-type guarantee; dynamic scaling for small repos |
| **Memory** | Persistent session observations + architectural decision records (FTS search) |
| **Multi-repo** | Workspace YAML, cross-repo link detection, unified ranked pack |
| **Graph viz** | Interactive D3.js HTML — color by kind or community cluster |
| **MCP server** | 8 tools over stdio JSON-RPC 2.0, compatible with Claude Code, Cursor, Windsurf |
| **Agent adapters** | Claude system prompt, Copilot instructions, Codex task prompt |
| **Benchmarks** | 20-task suite, 3 baselines, Markdown report |

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Install

```bash
git clone https://github.com/mohankrishnaalavala/context-router
cd context-router
uv sync --all-packages
```

> **PyPI install (coming soon):** `pip install context-router`

---

## Quickstart

```bash
# 1. Initialize a project (creates .context-router/ with config + SQLite DB)
uv run context-router init

# 2. Index the repository — extracts symbols, call edges, test links, communities
uv run context-router index

# 3. Generate a context pack for a code review
uv run context-router pack --mode review

# 4. Implement a feature — query-aware ranking surfaces the right files
uv run context-router pack --mode implement --query "add pagination to the users endpoint"

# 5. Debug a failure — parse an error file and rank by blast radius
uv run context-router pack --mode debug --error-file pytest-output.xml

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
| [`index`](#index) | Scan and index all source files |
| [`watch`](#watch) | Incrementally re-index on file save |
| [`pack`](#pack) | Generate a ranked context pack |
| [`explain`](#explain) | Explain the last pack's selections |
| [`memory`](#memory) | Add/search session observations |
| [`decisions`](#decisions) | Add/search architectural decision records |
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

**Token budget** (default: 8 000 tokens) is read from `.context-router/config.yaml`. Items are dropped lowest-confidence first, but at least one item per source category is always preserved.

The pack is saved to `.context-router/last-pack.json` for later inspection.

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
context-router explain last-pack [--json]
```

```
  [changed_file]  build_pack (orchestrator.py)       — Modified in current diff
  [blast_radius]  ContextRanker (ranker.py)           — Depends on a changed file
  [impacted_test] test_ranker.py                      — Tests code affected by this change
  [contract]      ContextItem (models.py)             — Data contract or interface definition
```

---

### `memory`

Persist and search session observations. Stored in the local SQLite DB with FTS5 full-text search.

```
context-router memory add --from-session SESSION.json
context-router memory search QUERY
context-router memory stale
```

`stale` lists observations whose referenced files no longer exist in the index.

**Examples:**

```bash
# Search for past observations about authentication
uv run context-router memory search "auth token"

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
```

`--status` accepts: `proposed` | `accepted` | `deprecated` | `superseded`

**Examples:**

```bash
# Record a new ADR
uv run context-router decisions add "Use SQLite for local storage" \
  --decision "SQLite + FTS5 chosen over PostgreSQL" \
  --context "Need offline-capable storage" \
  --status accepted

# Search decisions by keyword
uv run context-router decisions search "database"
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
```

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
context-router benchmark run [--project-root PATH] [--output PATH] [--json]
context-router benchmark report [--project-root PATH] [--input PATH] [--json]
```

See [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) for real numbers on the context-router codebase (**64.7% average token reduction, 131 ms average latency**).

---

### `mcp`

Start the context-router MCP server over stdio JSON-RPC 2.0, exposing all tools to any MCP-compatible AI coding agent.

```
context-router mcp
```

**Available MCP tools:**

| Tool | What it does |
|---|---|
| `build_index` | Full re-index of the repository |
| `update_index` | Incremental re-index for changed files |
| `get_context_pack` | Ranked pack for review / implement / debug / handover |
| `get_debug_pack` | Debug pack with optional error-file (pytest/JUnit XML) parsing |
| `explain_selection` | Why each item was selected + token count stats |
| `generate_handover` | Handover pack combining changes + memory + decisions |
| `search_memory` | Full-text search of session observations |
| `get_decisions` | Search or list architectural decision records |

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
  language-java/        # Java (stub)
  language-dotnet/      # .NET/C# (stub)
  memory/               # Observation store + FTS
  runtime/              # Stack trace + JUnit/pytest XML parsers
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

# Run all 403 tests
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

Measured on the context-router codebase itself (286 files, 1 765 symbols, 3 174 edges):

| Mode | Avg tokens selected | vs naive (all symbols) | Avg latency |
|---|---|---|---|
| review | 1 420 | −73% | 118 ms |
| implement | 1 680 | −68% | 124 ms |
| debug | 1 290 | −75% | 142 ms |
| handover | 1 510 | −71% | 139 ms |
| **overall** | **1 475** | **−64.7%** | **131 ms** |

See [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) for the full per-task breakdown.

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
