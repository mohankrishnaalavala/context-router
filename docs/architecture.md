# Architecture

context-router is a local-first CLI + MCP server that selects minimum useful
context for AI coding agents across code structure, runtime evidence, and
durable project memory.

## Package Layout

```
context-router/
├── apps/
│   ├── cli/            Phase 0 — Typer CLI (init implemented; others stubbed)
│   └── mcp-server/     Phase 5 — stdio MCP server (stub)
└── packages/
    ├── contracts/       Phase 0 — Pydantic models + plugin interfaces (NO business logic)
    ├── core/            Phase 0 — PluginLoader + Orchestrator stub
    ├── storage-sqlite/  Phase 0 — SQLite + FTS5, migrations, repository pattern
    ├── graph-index/     Phase 1 — file scanner, symbol graph, dependency edges
    ├── ranking/         Phase 2 — mode-specific rankers, token budget enforcer
    ├── runtime/         Phase 3 — stack trace, test failure, log parsers
    ├── memory/          Phase 4 — observations, decisions, stale detection
    ├── language-python/ Phase 1 — Python Tree-sitter analyzer
    ├── language-java/   Phase 1 — Java Tree-sitter analyzer
    ├── language-dotnet/ Phase 1 — C#/.NET Tree-sitter analyzer
    ├── language-yaml/   Phase 1 — YAML key-path analyzer
    ├── adapters-claude/ Phase 6 — Claude Code prompt adapter
    ├── adapters-copilot/Phase 6 — GitHub Copilot instructions adapter
    ├── adapters-codex/  Phase 6 — Codex subagent task adapter
    ├── workspace/       Phase 7 — multi-repo registry and cross-repo links
    └── benchmark/       Phase 8 — benchmark harness and sample task suite
```

## Module Boundaries

```
CLI / MCP server
      ↓ (only)
   core (Orchestrator, PluginLoader)
      ↓ (only)
   contracts (models + interfaces)
      ↑
storage-sqlite, ranking, graph-index, memory, runtime, language-*, adapters-*
```

- **contracts** has zero internal dependencies.
- All inter-module data exchange uses Pydantic models from `contracts`.
- Language analyzers never return raw Tree-sitter nodes.
- Storage is only accessed through repository interfaces in `storage-sqlite`.

## Data Flow (Phase 2+)

```
File system / git diff
        ↓
   graph-index (file scanner → symbols + edges)
        ↓
   storage-sqlite (SQLite + FTS5)
        ↓
   ranking (mode-specific ranker)
        ↓
   core/Orchestrator → ContextPack
        ↓
   CLI output / MCP tool response / adapter output
```

## Tech Stack

| Concern         | Choice                        |
|-----------------|-------------------------------|
| Language        | Python 3.12+                  |
| CLI             | Typer                         |
| Data contracts  | Pydantic v2                   |
| Storage         | SQLite + FTS5 (stdlib sqlite3)|
| Parsing         | Tree-sitter (Phase 1)         |
| File watching   | watchdog (Phase 1)            |
| Agent protocol  | MCP stdio transport (Phase 5) |
| Testing         | pytest                        |
| Package manager | uv (workspace mode)           |

## ADRs

- [0001 — Use SQLite + FTS5](adr/0001-use-sqlite-fts5.md)
- [0002 — Plugin discovery via entry_points](adr/0002-plugin-entry-points.md)
