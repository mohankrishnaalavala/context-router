# context-router

[![PyPI](https://img.shields.io/pypi/v/context-router-cli)](https://pypi.org/project/context-router-cli/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![MCP compatible](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io)
[![Tests](https://github.com/mohankrishnaalavala/context-router/actions/workflows/ci.yml/badge.svg)](https://github.com/mohankrishnaalavala/context-router/actions)
[![SafeSkill 93/100](https://img.shields.io/badge/SafeSkill-93%2F100_Verified%20Safe-brightgreen)](https://safeskill.dev/scan/mohankrishnaalavala-context-router)

> **Memory-aware context engine for AI coding agents.**
> Persistent project memory · multi-repo workspaces · up to **91% fewer tokens** (89% combined avg across 6 OSS projects, 17/18 rank-1) · MCP-native, local-first.

context-router is **more than a context picker**. It indexes your code,
**remembers what your team learned** (observations + decisions, shared
via git), and gives every coding agent the *minimum useful* slice of
both — so each session compounds on the last instead of starting from
zero.

```text
┌─ your repo ──────────────────────┐    ┌─ pack (~159 tokens) ────────┐
│ 50,000 LOC, 12,000 symbols       │ →  │ • src/auth/cache.py         │
│ + .context-router/memory/*.md    │    │ • tests/test_auth_cache.py  │
│ + workspace.yaml (multi-repo)    │    │ • ADR-0014: TTL grace policy│
└──────────────────────────────────┘    └─────────────────────────────┘
                  ↑ ranker uses code structure, query, freshness, memory
```

---

## Three things that make it different

### 🧠 Memory that compounds

Every fix, decision, and hard-won lesson becomes a **markdown observation**
in `.context-router/memory/`. Commit it to git — your whole team shares
it. Future agents call `search_memory` and get the answer in one MCP call
instead of re-deriving it from the diff history. **No SaaS, no lock-in,
no separate backend** — memory is shipped via your existing git flow.

Two kinds of memory, both first-class:

| Type | Captures | Used by |
|---|---|---|
| **Observations** | Bug fixes, perf wins, gotchas, "why this looks weird" | Future debug/implement packs auto-recall related entries |
| **Decisions (ADRs)** | Library picks, pattern choices, schema changes — with rationale | Surfaced in handover packs and during implement queries that touch the area; supersession lifecycle preserved |

Two more multipliers:

- **Auto-capture hooks** (`setup --with-hooks`): a git post-commit hook saves an observation per commit; a Claude Code PostToolUse hook saves on every Edit/Write. Memory builds up silently while you work.
- **Feedback learning** (`record_feedback`): each pack's useful/missing/noisy reports tune per-file confidence after ≥3 reports — query-similarity-weighted since v4.4.2 so feedback for one query doesn't poison unrelated ones.

### 🔗 Multi-repo workspaces, not just monorepos

Most context tools assume one repo. context-router treats a workspace
of N repos as one searchable graph: `workspace detect-links` infers
cross-repo edges from Python imports + OpenAPI / protobuf / GraphQL
contracts; `workspace pack` returns a unified ranked pack with
`[repo]` labels and warns when edges cross community boundaries.

### ⚡ Up to 91% token reduction without losing recall

Latest holdout against six OSS projects in five languages:

| Suite | Repos | Avg F1 | Rank-1 | Avg tokens / pack | vs ~1,506 baseline |
|---|---|---:|---:|---:|---:|
| A | gin · actix-web · django | 0.630 | 8/9 | 186 | **−87.7%** |
| B | gson · requests · zod | **0.685** | **9/9** | **132** | **−91.2%** |
| **Combined** | 6 projects, 5 languages | **0.658** | **17/18 (94%)** | **159** | **−89.4%** |

Comparable tools average ~1,506 tokens per pack on the same workload.
Full per-task breakdown + reproduction in [`BENCHMARKS.md`](BENCHMARKS.md).

---

## 60-second quickstart

```bash
# Install (uv recommended; pipx / pip / brew also work — see AGENT_GUIDE.md)
# Default — Python · TypeScript / JavaScript · Java · C# · YAML · SQL
uv tool install context-router-cli
# OR for polyglot / monorepo users — adds Go · Rust · Ruby · PHP parsers
uv tool install 'context-router-cli[all-languages]'

# In your repo:
context-router init                      # creates .context-router/
context-router setup --with-hooks        # configure agent + auto-capture
context-router index                     # scan symbols/edges (<30s typical)

# Use it
context-router pack --mode review                                 # for a PR
context-router pack --mode implement --query "add rate limiting"  # for a feature
context-router pack --mode debug --error-file pytest.xml          # for a failure
```

For the full setup walkthrough — including MCP server registration for
Claude Code, Cursor, Copilot, Gemini, Windsurf, and Codex — see
[`AGENT_GUIDE.md`](AGENT_GUIDE.md). **Hand `AGENT_GUIDE.md` to a local
agent and it can install, configure, and start using context-router on
its own.**

---

## Pack modes at a glance

| Mode | Use when | Default budget |
|---|---|---:|
| `review` | Reading a diff / PR | 1,500 tok |
| `implement` | Writing new code per a query | 1,500 tok |
| `debug` | Tracing a failure | 2,500 tok |
| `handover` | Onboarding / sprint summary (or `--wiki` for deterministic markdown) | 4,000 tok |
| `minimal` | Quick triage — ≤5 items + `next_tool_suggestion` | 800 tok |

Optional flags: `--with-rerank` (cross-encoder, +0.10–0.20 precision),
`--with-semantic` (bi-encoder cosine), `--max-tokens N`,
`--inline-bodies {top1|all|none}`, `--json`. Pack metadata exposes
`depth` (`narrow`/`standard`/`broad`) and `feedback_applied` so you
can see which historical signals shaped the result.

> `--with-rerank` and `--with-semantic` need the optional `[semantic]`
> extra (~22 MB cross-encoder + bi-encoder weights, downloaded once):
> `uv tool install 'context-router-cli[semantic]'` (or `pipx install
> 'context-router-cli[semantic]'`). Without it, both flags log a warning
> and silently fall through to the structural ranker.

---

## MCP integration

context-router exposes **17 MCP tools** over stdio JSON-RPC 2.0.
Compatible with Claude Code, Cursor, Copilot, Gemini CLI, Windsurf,
and any other MCP-aware agent.

<details>
<summary><strong>Claude Code — <code>.mcp.json</code></strong></summary>

```json
{
  "mcpServers": {
    "context-router": { "command": "context-router", "args": ["mcp"], "type": "stdio" }
  }
}
```
</details>

<details>
<summary><strong>Cursor — <code>.cursor/mcp.json</code></strong></summary>

```json
{
  "mcpServers": {
    "context-router": { "command": "context-router", "args": ["mcp"], "cwd": "${workspaceFolder}" }
  }
}
```
</details>

<details>
<summary><strong>Windsurf — <code>.windsurf/mcp_config.json</code></strong></summary>

```json
{
  "servers": {
    "context-router": { "command": "context-router mcp", "transport": "stdio" }
  }
}
```
</details>

<details>
<summary><strong>Gemini CLI — <code>~/.gemini/settings.json</code></strong></summary>

```json
{
  "mcpServers": {
    "context-router": { "command": "context-router", "args": ["mcp"] }
  }
}
```
</details>

`context-router setup --agent <name>` writes the right config for you.
Run `context-router doctor` to verify the agent can reach the server.

**Tool surface:** `get_context_pack` · `get_debug_pack` ·
`get_minimal_context` · `generate_handover` · `explain_selection` ·
`build_index` · `update_index` · `get_call_chain` · `suggest_next_files` ·
`save_observation` · `search_memory` · `list_memory` ·
`save_decision` · `get_decisions` · `mark_decision_superseded` ·
`record_feedback` · `get_context_summary`.

Full tool reference and the **agent-contract section** every coding
agent should follow live in [`AGENT_GUIDE.md`](AGENT_GUIDE.md).

---

## Language support

**Default install** (`uv tool install context-router-cli`):
Python · TypeScript / JavaScript (`.ts`/`.tsx`/`.js`/`.jsx`/`.mjs`/`.cjs`)
· Java (full, with `enum`) · .NET / C# (full, with `record` / `enum`) ·
YAML (`.yaml`/`.yml` — k8s / Helm / GitHub Actions) · SQL DDL
(`CREATE TABLE / VIEW / FUNCTION / PROCEDURE` via regex).

**`[all-languages]` extra** (`uv tool install 'context-router-cli[all-languages]'`):
adds Go · Rust · Ruby · PHP via tree-sitter. The analyzer source ships in
every wheel; the extra only adds the optional tree-sitter parser deps.
Without the parsers, the entry points still register and `context-router
doctor` reports a stderr warning per missing parser — silent skipping is
forbidden by the no-silent-failure policy.

Add another language by implementing the `LanguageAnalyzer` protocol
and registering via the `context_router.language_analyzers` entry
point — `context-router index` picks it up automatically.

---

## Architecture (one screen)

```
packages/
  contracts/         # Pydantic models + plugin protocols (no internal deps)
  storage-sqlite/    # SQLite + FTS5, migrations, repositories
  graph-index/       # File scanner, language dispatch, git diff, communities
  ranking/           # BM25 + freshness + semantic + cross-encoder + score floor
  core/              # Orchestrator — wires storage + graph + ranking
  language-{python,typescript,java,dotnet,yaml}/  # tree-sitter analyzers
  memory/            # Observations + FTS + freshness + export
  runtime/           # Stack trace + JUnit/pytest XML parsers
  workspace/         # Multi-repo workspace support
  benchmark/         # 20-task suite + holdout runner
apps/
  cli/               # Typer CLI
  mcp-server/        # MCP server entry point
```

Strict module boundaries (CI-enforced): `contracts` has zero internal
deps; only `storage-sqlite` touches SQLite; only `core` imports from
`storage-sqlite`/`graph-index`/`ranking`; CLI/MCP only import `core`
and `benchmark`.

---

## Documentation

| Doc | For |
|---|---|
| [`AGENT_GUIDE.md`](AGENT_GUIDE.md) | **Hand to your AI agent** — install, setup, every feature, the agent contract, troubleshooting, examples |
| [`BENCHMARKS.md`](BENCHMARKS.md) | Full holdout results across 6 OSS projects, reproduction commands, fixture provenance |
| [`CHANGELOG.md`](CHANGELOG.md) | Per-release detail (current: v4.4.3) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Development setup, coding standards, PR process |

---

## Development

```bash
git clone https://github.com/mohankrishnaalavala/context-router
cd context-router
uv sync --all-packages --extra dev
uv run pytest --tb=short -q     # 476 tests, ~60s
uv run ruff check .
```

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
