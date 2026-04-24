# Project Overview
<!-- Last updated: 2026-04-24 · v4.2.0 current, v4.3 planned -->

context-router is a local-first CLI tool and MCP server that selects the minimum useful context for AI coding agents working on real engineering tasks. Instead of letting agents blindly open files, keyword-grep, or re-read the entire codebase, context-router routes each task through a ranked combination of code structure, runtime evidence, and durable project memory to produce a compact, explainable context pack.

The core promise is: given a task and a mode (review, debug, implement, handover), return the smallest useful set of code files, test references, logs, decisions, and prior observations — with a reason and confidence score for every item. The product is measurably better than naive file reading and is benchmarkable against graph-only baselines like code-review-graph.

The product is intentionally local-first and requires no API key for core features. It integrates with Claude Code, GitHub Copilot, and Codex-style agents through MCP and thin adapter modules. It supports Python, Java, C#/.NET, and YAML. Multi-repo workspace support (up to 3 repos) is a first-class design concern built into the architecture from Phase 0.

The vision is to become the routing layer that sits between a coding agent and a repository: not a replacement for the agent's reasoning, but the piece that decides what evidence the agent should reason about. The architecture is fully modular and loosely coupled so that new languages, runtime sources, ranking strategies, and agent adapters can be added without rewriting the core.

## Current release: v4.2.0 (2026-04-24)

### Shipped features by phase

**v4.0 — Evaluation & Workspace DB**
- `context-router eval --queries <path> --json`: Recall@K / Precision@K / F1@K evaluation harness
- `context-router workspace sync`: rebuilds cross-repo edge cache into `.context-router/workspace.db`
- CI synthetic recall gate: enforces Recall@20 ≥ 0.65 on every PR
- `WorkspaceOrchestrator.cross_repo_edges_for_repo()`: reads pre-built edges from workspace.db

**v4.1 — Memory-as-Code**
- `save_observation` dual-writes: SQLite (primary) + git-tracked `.md` file under `.context-router/memory/observations/`
- Write gate: rejects observations with summary < 60 chars or empty `files_touched` — warns to stderr, no silent drops
- `pack --use-memory` / MCP `get_context_pack use_memory: true`: injects up to 8 BM25+recency-ranked memory hits
- `memory migrate-from-sqlite`: backfills existing SQLite observations to git-tracked `.md` files
- `memory show <id>`: look up a saved observation by exact or prefix ID
- License: Apache 2.0

**v4.2 — Memory Quality**
- **Memory sub-budget cap**: memory items capped at 15% of total token budget; configurable via `memory_budget_pct`; values out of range warn to stderr and fall back to 0.15
- **Adaptive top-k**: trailing items with confidence < 0.6× leader are dropped in `review`/`implement` modes; `debug`/`handover` return all budget-admitted items
- **Observation provenance**: `MemoryHit.provenance` classifies each observation as `committed`, `staged`, or `branch_local` via `git ls-files`; non-committed observations are filtered from main-branch packs
- `budget: {total_tokens, memory_tokens, memory_ratio}` in all `--json` pack outputs
- `memory_hits_summary: {committed, staged}` alongside `memory_hits` in JSON output

### Upcoming: v4.3 — Staleness & Federation
See [.handover/work/tasks.md](../work/tasks.md) for planned scope.

## Architecture at a glance

```
context-router/
├── apps/cli/             — Typer CLI entrypoint (thin shell over core)
├── apps/mcp-server/      — MCP stdio server (thin shell over core)
└── packages/
    ├── contracts/        — Shared Pydantic schemas, plugin interfaces
    ├── core/             — Orchestration, use-case coordinators, plugin loader
    ├── graph-index/      — File scanner, symbol graph, dependency edges, test mapping
    ├── memory/           — Observations (.md + SQLite), decisions, provenance, stale detection
    ├── runtime/          — Stack trace, test failure, log, lint parsers
    ├── ranking/          — Mode-specific rankers, token budget, adaptive top-k, explain output
    ├── language-*/       — Per-language Tree-sitter analyzers (python, java, dotnet, yaml)
    ├── adapters-*/       — Agent adapters (claude, copilot, codex)
    ├── storage-sqlite/   — Repository pattern over SQLite, migrations
    ├── workspace/        — Multi-repo registry, cross-repo link model, workspace.db
    └── benchmark/        — Eval harness, baselines, recall/precision gate, report generation
```

All modules communicate through typed contracts in `packages/contracts`. No module imports implementation details from another.
