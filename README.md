# context-router

A local-first CLI and MCP server that selects the **minimum useful context** across code structure, runtime evidence, and project memory for AI coding agents — reducing token consumption on review, debug, implement, and handover tasks.

## Why

AI coding agents work best when given focused, relevant context rather than entire codebases. context-router:

- Indexes your repo's symbols and dependency edges into a local SQLite database
- Ranks candidate context items by structural relevance and recency for a given task mode
- Enforces a configurable token budget so your agent prompt stays lean
- Explains every selection decision in one human-readable sentence

No API key required. Everything runs locally.

## Status

| Phase | What | Status |
|---|---|---|
| 0 — Foundation | Monorepo, contracts, storage, CLI shell | ✅ Done |
| 1 — Indexing | File scanner, language analyzers, symbol graph | ✅ Done |
| 2 — Context Packs v1 | Ranking engine, `pack`, `explain` commands | ✅ Done |
| 3 — Debug Layer | Runtime signal parsers (JUnit, stack trace, log, dotnet), debug ranker | ✅ Done |
| 4 — Memory & Decisions | Observation store, ADR retrieval, `memory` + `decisions` commands | ✅ Done |
| 5 — MCP Server | 8 MCP tools over stdio JSON-RPC 2.0, `mcp` command | ✅ Done |
| 6 — Adapters | Claude, Copilot, Codex prompt/instructions generators | ✅ Done |
| 7 — Multi-Repo | Workspace registry, cross-repo link detection + ranking, `workspace` commands | ✅ Done |
| 8 — Benchmarks | 20-task harness, 3 baselines, JSON + Markdown reports, [results](BENCHMARK_RESULTS.md) | ✅ Done |

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager

## Install

```bash
git clone https://github.com/mohankrishnaalavala/context-router
cd context-router
uv sync --all-packages
```

## Quickstart

```bash
# 1. Initialise a project (creates .context-router/ with config + SQLite DB)
uv run context-router init

# 2. Index the repository
uv run context-router index

# 3. Generate a context pack for a code review
uv run context-router pack --mode review

# 4. Generate a context pack for a new feature
uv run context-router pack --mode implement --query "add pagination to the users endpoint"

# 5. Explain what was selected and why
uv run context-router explain last-pack

# 6. Get machine-readable JSON for use in scripts or agent prompts
uv run context-router pack --mode review --json
```

## Commands

### `init`

Initialise a project directory.

```
context-router init [--project-root PATH] [--json]
```

Creates `.context-router/config.yaml` and `.context-router/context-router.db`.

---

### `index`

Scan and index the repository into SQLite.

```
context-router index [--project-root PATH] [--repo REPO_NAME]
```

Walks all source files, runs language analysers, and writes symbols + dependency edges to the local DB. Language analyzers are discovered via Python entry points (`context_router.language_analyzers`). Currently ships with a full Python analyser; Java, .NET, and YAML analysers are stubbed.

---

### `watch`

Watch for file changes and incrementally re-index.

```
context-router watch [--project-root PATH]
```

---

### `pack`

Generate a ranked context pack.

```
context-router pack --mode MODE [--query TEXT] [--project-root PATH] [--json]
```

**Modes:**

| Mode | Ranking priority |
|---|---|
| `review` | changed files → blast radius → impacted tests → config |
| `implement` | entrypoints → contracts/interfaces → extension points → functions |
| `debug` | runtime signal match → failing tests → changed files → blast radius |
| `handover` | recent changes → memory observations → decisions → blast radius |

The pack is saved to `.context-router/last-pack.json` for later inspection.

**Token budget** is read from `.context-router/config.yaml` (default: 8 000 tokens). Items are dropped lowest-confidence first, but at least one item per category is always preserved.

---

### `explain`

Explain the last generated context pack.

```
context-router explain last-pack [--json]
```

Prints one line per selected item:
```
  [changed_file] build_pack (orchestrator.py)
    Modified in current diff
  [contract] ContextItem (models.py)
    Data contract or interface definition
```

---

### `memory`

Add and search session observations (persisted to the local SQLite DB).

```
context-router memory add --from-session SESSION.json
context-router memory search QUERY
context-router memory stale
```

`stale` lists observations whose referenced files no longer exist in the index.

---

### `decisions`

Manage architectural decision records (ADRs).

```
context-router decisions add TITLE [--decision TEXT] [--context TEXT] [--consequences TEXT] [--tags TAGS] [--status STATUS]
context-router decisions search QUERY
context-router decisions list
```

`--status` accepts: `proposed` | `accepted` | `deprecated` | `superseded`

---

### `mcp`

Start the MCP server over stdio JSON-RPC 2.0 transport, exposing all 8 context-router tools to any MCP-compatible AI coding agent.

```
context-router mcp
```

**Available MCP tools:**

| Tool | Description |
|---|---|
| `build_index` | Full re-index of the repository |
| `update_index` | Incremental re-index for changed files |
| `get_context_pack` | Ranked context pack for review/implement/debug/handover |
| `get_debug_pack` | Debug pack with optional error-file parsing |
| `explain_selection` | Why each item was selected + token stats |
| `generate_handover` | Handover pack (changes + memory + decisions) |
| `search_memory` | Full-text search of session observations |
| `get_decisions` | Search or list architectural decisions |

**Claude Code configuration** — add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "context-router": {
      "command": "context-router",
      "args": ["mcp"]
    }
  }
}
```

---

### Adapters (Phase 6)

Generate agent-specific output from a ContextPack programmatically:

```python
from adapters_claude import ClaudeAdapter
from adapters_copilot import CopilotAdapter
from adapters_codex import CodexAdapter
from core.orchestrator import Orchestrator

pack = Orchestrator().build_pack("review", "fix the auth bug")
print(ClaudeAdapter().generate(pack))   # system-prompt preamble
print(CopilotAdapter().generate(pack))  # .github/copilot-instructions.md content
print(CodexAdapter().generate(pack))    # Codex subagent task prompt
```

---

### `workspace`

Manage multi-repo workspaces with cross-repo context packs.

```
context-router workspace init [--root PATH] [--name NAME]
context-router workspace repo add NAME PATH [--root PATH] [--language LANG]
context-router workspace repo list [--root PATH] [--json]
context-router workspace link add FROM TO [--root PATH]
context-router workspace pack --mode MODE [--query TEXT] [--root PATH] [--json]
```

Creates `workspace.yaml` to track multiple repos. `workspace pack` generates a
context pack across all repos, labelling items with `[repo-name]` and applying
a confidence boost to items in linked (dependency) repos.

---

### `benchmark`

Run the 20-task benchmark suite and report token reduction metrics.

```
context-router benchmark run [--project-root PATH] [--output PATH] [--json]
context-router benchmark report [--project-root PATH] [--input PATH] [--json]
```

See [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md) for real measured numbers on
the context-router codebase (64.7% average token reduction, 131 ms avg latency).

## Configuration

Edit `.context-router/config.yaml`:

```yaml
# Maximum tokens for a generated context pack
token_budget: 8000

capabilities:
  # Enable LLM-powered summarisation (requires API key)
  llm_summarization: false

# fnmatch patterns to exclude from indexing
ignore_patterns:
  - ".git"
  - "__pycache__"
  - "*.pyc"
  - "*.egg-info"
  - ".venv"
```

## Architecture

context-router is a uv workspace of focused packages:

```
packages/
  contracts/        # Pydantic models + plugin interfaces (no internal deps)
  storage-sqlite/   # SQLite DB, migrations, repositories
  graph-index/      # File scanner, language analyzer dispatch, git diff
  ranking/          # Token estimator, ContextRanker, budget enforcer
  core/             # Orchestrator — wires storage + graph + ranking
  language-python/  # Python AST analyzer (tree-sitter)
  language-java/    # Java analyzer (stub)
  language-dotnet/  # .NET/C# analyzer (stub)
  language-yaml/    # YAML key-path + k8s/CI analyzer (stub)
  memory/           # Observation and decision store (Phase 4)
  runtime/          # Stack trace + test XML parsers (Phase 3)
  ranking/          # Context ranker + token budget (Phase 2)
  workspace/        # Multi-repo workspace support (Phase 7)
  benchmark/        # Benchmark harness (Phase 8)
  adapters-claude/  # Claude prompt adapter (Phase 6)
  adapters-copilot/ # GitHub Copilot adapter (Phase 6)
  adapters-codex/   # Codex adapter (Phase 6)
apps/
  cli/              # Typer CLI (context-router command)
  mcp-server/       # MCP server (Phase 5)
```

**Module boundary rules** (enforced in CI):

- `contracts` has no internal dependencies
- Only `storage-sqlite` may import SQLite
- Only `core` imports from `storage-sqlite`, `graph-index`, and `ranking`
- CLI and MCP server only import from `core`

## Development

```bash
# Install all packages + dev dependencies
uv sync --all-packages --extra dev

# Run tests
uv run pytest --tb=short -q

# Lint
uv run ruff check .

# Install git pre-push hook (runs tests before every push)
git config core.hooksPath .githooks
```

## Contributing

See `.handover/` for architecture context, decision records, and open tasks. The task list is at `.handover/work/tasks.md`.

Language analyzer plugins can be added as separate packages by implementing the `LanguageAnalyzer` protocol from `contracts.interfaces` and registering via:

```toml
[project.entry-points."context_router.language_analyzers"]
py = "language_python:PythonAnalyzer"
```

## License

MIT — see [LICENSE](LICENSE).
