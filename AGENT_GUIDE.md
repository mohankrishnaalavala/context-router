# Agent Guide — context-router

> **Hand this file to your AI coding agent.** It contains everything an
> agent needs to install, configure, and use context-router on a fresh
> project: prerequisites, install commands, MCP registration for every
> supported agent, the full feature reference, and the **memory contract**
> agents must follow for context-router to compound value over time.

If you are a human reading this: the README has the marketing pitch and
the 60-second quickstart. This document is the long-form reference.

---

## Table of contents

1. [Prerequisites](#1-prerequisites)
2. [Install](#2-install)
3. [First-time project setup](#3-first-time-project-setup)
4. [Register the MCP server with your agent](#4-register-the-mcp-server-with-your-agent)
5. [The agent contract — what an agent MUST do](#5-the-agent-contract--what-an-agent-must-do)
6. [Feature reference](#6-feature-reference)
7. [Worked examples](#7-worked-examples)
8. [Multi-repo workspaces](#8-multi-repo-workspaces)
9. [Troubleshooting](#9-troubleshooting)
10. [Performance expectations](#10-performance-expectations)

---

## 1. Prerequisites

- **Python 3.12+** (`python3 --version`)
- **`uv`** — fast Python package manager. Install once:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Git** (any version) — context-router reads diffs and commit history.
- An MCP-compatible coding agent: **Claude Code**, **Cursor**, **GitHub
  Copilot**, **Gemini CLI**, **Windsurf**, or **OpenAI Codex**. Plain
  CLI usage works without any agent.

## 2. Install

Pick one:

```bash
# uv (recommended — installs into an isolated tool environment)
uv tool install context-router-cli
# Add semantic / rerank support (~22 MB sentence-transformers weights):
uv tool install 'context-router-cli[semantic]'

# Homebrew (macOS / Linux)
brew tap mohankrishnaalavala/context-router
brew install context-router

# pipx
pipx install context-router-cli

# pip (system / venv)
pip install context-router-cli

# From source (development)
git clone https://github.com/mohankrishnaalavala/context-router
cd context-router && uv sync --all-packages
```

Verify:

```bash
context-router --version
```

## 3. First-time project setup

Run from the **root of the repo you want to index**:

```bash
# 1. Create .context-router/ (config + SQLite DB)
context-router init

# 2. Configure your AI coding agent(s). Auto-detects from existing
#    config files; pass --agent NAME to target one explicitly.
context-router setup                    # detects and configures all
context-router setup --agent claude     # just Claude Code
context-router setup --agent all        # configure every supported agent

# 3. (Recommended) install auto-capture hooks so memory accrues
#    silently from commits and Claude-Code edits.
context-router setup --with-hooks

# 4. Build the symbol/edge index. Takes <30s on most repos; one-time.
context-router index

# 5. (Optional) start a watcher for incremental re-index on file save.
context-router watch &
```

After step 4 you can immediately generate context packs:

```bash
context-router pack --mode review                       # for the current diff
context-router pack --mode implement --query "add X"    # for a feature
context-router pack --mode debug --error-file err.log   # for a failure
```

### What `setup` writes

| Agent | File | Notes |
|---|---|---|
| Claude Code | `CLAUDE.md` + `.mcp.json` | Appends a managed `<!-- context-router: setup -->` block; idempotent |
| GitHub Copilot | `.github/copilot-instructions.md` | Compact bullet rules |
| Cursor | `.cursorrules` | Imperative one-liners |
| Windsurf | `.windsurfrules` | Rules + 1–2 invocation examples |
| Codex / OpenAI agents | `AGENTS.md` | Markdown block, same contract |
| Gemini CLI | (no dedicated block — reads `AGENTS.md`, also works with `CLAUDE.md`) | Run `setup --agent codex` to populate `AGENTS.md`; configure MCP server in `~/.gemini/settings.json` (see § 4) |

Re-running `context-router setup` is idempotent (skips files already
configured). To **upgrade** existing instruction blocks to the latest
contract after a context-router release, pass `--upgrade`:

```bash
context-router setup --upgrade           # rewrites instruction blocks in-place
context-router setup --with-hooks --upgrade  # also refreshes hook scripts
```

## 4. Register the MCP server with your agent

`context-router setup --agent claude` writes `.mcp.json` automatically.
For other agents, here is the canonical config (copy-paste):

### Claude Code — `.mcp.json` in project root

```json
{
  "mcpServers": {
    "context-router": {
      "command": "context-router",
      "args": ["mcp"],
      "type": "stdio"
    }
  }
}
```

### Cursor — `.cursor/mcp.json`

```json
{
  "mcpServers": {
    "context-router": {
      "command": "context-router",
      "args": ["mcp"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

### Windsurf — `.windsurf/mcp_config.json`

```json
{
  "servers": {
    "context-router": {
      "command": "context-router mcp",
      "transport": "stdio"
    }
  }
}
```

### GitHub Copilot — `.github/copilot-instructions.md` (written by `setup`)

Copilot's MCP support is configured in your IDE (VS Code: workspace
`settings.json` under `"github.copilot.chat.mcp.servers"`):

```json
{
  "github.copilot.chat.mcp.servers": {
    "context-router": { "command": "context-router", "args": ["mcp"] }
  }
}
```

The instruction block written to `.github/copilot-instructions.md`
tells Copilot to call the MCP tools.

### Codex / OpenAI agents — `AGENTS.md` block + workspace MCP config

`context-router setup --agent codex` writes the instruction block to
`AGENTS.md`. Codex picks up MCP servers from your shell environment or
a workspace `.codex/mcp.json`:

```json
{
  "mcpServers": {
    "context-router": { "command": "context-router", "args": ["mcp"], "type": "stdio" }
  }
}
```

### Gemini CLI — `~/.gemini/settings.json`

```json
{
  "mcpServers": {
    "context-router": { "command": "context-router", "args": ["mcp"] }
  }
}
```

Gemini reads the same instruction text from `AGENTS.md` (or `CLAUDE.md`
if present) — `setup --agent codex` covers both Codex and Gemini.

Verify the server is reachable from your agent — you should see
context-router's tools listed under MCP. From Claude Code, run `/mcp`.

---

## 5. The agent contract — what an agent MUST do

context-router only compounds value if the agent **actually uses it**.
Most features need an explicit tool call. Treat the rules below as
non-negotiable when working in a context-router-enabled repo.

### Five rules

1. **At session start, search memory first.**
   Before grepping, globbing, or reading files for an unfamiliar topic,
   call `search_memory` with terms from the user's request. Past
   observations frequently contain the answer or a strong pointer.

2. **Pack before you read.**
   Call `get_context_pack` (or `get_debug_pack` / `get_minimal_context`)
   for the task at hand and read the returned items. Do **not** start
   with `Grep`/`Glob` over the whole repo — packs are typically 10–100×
   cheaper in tokens and surface the structurally-relevant files.

3. **Save observations after non-trivial work.**
   After fixing a bug, adding a feature, or learning a non-obvious
   constraint, call `save_observation` with a 1-line summary, the
   `task_type`, and the `files_touched`. Auto-capture hooks (if
   installed) cover commits, but mid-session learnings need an
   explicit save.

4. **Record decisions when you make them.**
   When you choose a library, adopt a pattern, change a schema, or
   reverse a previous decision — call `save_decision` with the
   rationale. Reversing? Use `mark_decision_superseded` to link the
   old decision to the new one. The audit trail matters.

5. **Close the loop with feedback.**
   After consuming a pack, call `record_feedback` with `--useful yes/no`
   and (if relevant) the `--missing` and `--noisy` file lists. After
   ≥3 reports per file the ranker self-tunes. Skipping this leaves the
   ranker blind.

### Negative rules — MUST NOT

- **Multi-file `Grep`/`Glob` without a prior pack call is a contract
  violation in this repo.** Single-file `Read` calls on paths returned
  by a pack are fine; whole-repo searches are not.
- **MUST NOT skip `save_observation` because "the user can read git log".**
  Memory is queryable, summarised, decay-scored, and survives across
  repos and sessions; commits are not.
- **MUST NOT save observations for trivial work** (typo fixes, formatter
  runs, dependency bumps). Save what a future agent would benefit from
  knowing — bug root-causes, perf wins, gotchas, design rationale.

### When in doubt

Call `get_minimal_context(query)` first — it returns ≤5 items plus a
`next_tool_suggestion` field that names the right follow-up tool.

### When auto-capture hooks are installed

`context-router setup --with-hooks` installs:

- A **git post-commit hook** that auto-saves an observation per commit
  with the commit message + changed files.
- A **Claude Code PostToolUse hook** (`.claude/settings.json`) that
  auto-saves on every `Edit`/`Write`/`MultiEdit` tool call.

**Hooks coexistence policy** — important to avoid double-saves:

- If the post-commit hook is installed, the agent should **not** call
  `save_observation` per commit. The hook handles it.
- If the PostToolUse hook is installed, the agent **MUST NOT** call
  `save_observation` per file edit. The hook handles it.
- Manual `save_observation` calls should be reserved for **synthesis** —
  root causes, gotchas, abandoned approaches, design rationale — that
  no single edit or commit captures.

To check which hooks are installed: read `.git/hooks/post-commit` and
`.claude/settings.json` (look for `hooks.PostToolUse` containing
`context-router memory capture`).

---

## 6. Feature reference

Every shipped capability, grouped by category. Each entry lists the
CLI command and the equivalent MCP tool name in `(parens)` when one
exists.

### Indexing

| Command | Purpose |
|---|---|
| `context-router init` | Create `.context-router/` config + SQLite DB |
| `context-router index` (`build_index`) | Full re-scan of the repo |
| `context-router watch` (`update_index`) | Incremental re-index on file save |
| `context-router doctor` | Diagnostic — checks index freshness, MCP wiring, hook installation |

### Context packs

| Command | Purpose | Default budget |
|---|---|---:|
| `pack --mode review` (`get_context_pack`) | PR / diff review — changed files + blast radius | 1,500 |
| `pack --mode implement --query "..."` (`get_context_pack`) | Building new code per a query — entrypoints + contracts + extension points | 1,500 |
| `pack --mode debug --query "..." [--error-file f]` (`get_debug_pack`) | Tracing a failure — runtime signals + failing tests + call chain | 2,500 |
| `pack --mode handover` (`generate_handover`) | Onboarding / sprint summary — recent changes + memory + decisions | 4,000 |
| `pack --mode handover --wiki` | Deterministic markdown subsystem wiki (no ranker, no LLM) — top communities → key files + hub symbols | n/a |
| `pack --mode minimal --query "..."` (`get_minimal_context`) | ≤5 items under 800 tokens + `next_tool_suggestion` hint | 800 |
| (MCP only) `get_context_summary` | Compact summary of the last pack — paths + reasons, no item bodies | n/a |
| (MCP only) `suggest_next_files` | Suggest likely-next files based on graph adjacency from a seed file | n/a |

**Pack flags:**
- `--with-rerank` — second-stage cross-encoder rerank over top-30 candidates (~22 MB model, ~50 ms latency, +0.10–0.20 precision lift on query-driven packs). **Requires the `[semantic]` extra** — install with `uv tool install 'context-router-cli[semantic]'` or `pipx install 'context-router-cli[semantic]'`. Without it the flag logs a warning and silently falls through to the structural ranker.
- `--with-semantic` — semantic boost via bi-encoder (cosine similarity over pre-computed embeddings; off-the-shelf when `embeddings` table empty). Same `[semantic]` extra required.
- `--max-tokens N` — single-call budget override
- `--inline-bodies {top1|all|none}` — inline symbol bodies into the pack response (top-1 default; `all` opts in to bigger packs)
- `--json` — machine-readable output (recommended for agent consumption)

**Pack metadata** (in `--json` output):
- `metadata.depth` ∈ `{narrow, standard, broad}` — adaptive depth based on top-1 confidence and the gap to top-2
- `metadata.depth_reason` — one-line explanation
- `metadata.feedback_applied` — historical feedback signals that shaped the result, as `[{path, delta}, …]`

### Memory

| Command | MCP tool | Purpose |
|---|---|---|
| `memory capture SUMMARY [...]` | `save_observation` | Save a 1-line observation with `--task-type`, `--files`, `--commit`, `--fix` |
| `memory add --stdin` / `--from-session` | `save_observation` | Bulk-import from JSON |
| `memory search QUERY` | `search_memory` | FTS5 search across all observations |
| `memory list [--sort freshness\|recency\|confidence]` | `list_memory` | List observations |
| `memory stale` | — | List observations referencing files that no longer exist |
| `memory export [--output PATH] [--redacted]` | — | Single-Markdown export for team sharing |

**Storage:** observations live in `.context-router/memory/observations/<id>.md`
as plain markdown. Commit them to git so your team shares them.
**Freshness scoring:** `effective_confidence = min(0.95, confidence × decay + access_boost)`
with a 30-day half-life; each search access adds `+0.02` (capped at `+0.20`).
Stale observations fade gracefully rather than being deleted.

### Decisions (ADRs)

| Command | MCP tool | Purpose |
|---|---|---|
| `decisions add TITLE [...]` | `save_decision` | Record a new architectural decision with `--decision`, `--context`, `--consequences`, `--status` |
| `decisions search QUERY` | `get_decisions` | FTS5 search across title/context/decision |
| `decisions list` | `get_decisions` | List all decisions |
| `decisions supersede OLD_ID NEW_ID` | `mark_decision_superseded` | Link an obsoleted decision to its replacement |
| `decisions export --output-dir PATH [--status accepted\|all]` | — | Per-ADR markdown files with slug filenames |

Statuses: `proposed` / `accepted` / `deprecated` / `superseded`.

### Feedback (closes the learning loop)

| Command | MCP tool | Purpose |
|---|---|---|
| `feedback record --pack-id ID [--useful y/n] [--missing FILES] [--noisy FILES] [--files-read FILES] [--reason TEXT]` | `record_feedback` | Per-pack feedback |
| `feedback stats` | — | Aggregate usefulness % + top missing/noisy files |
| `feedback list [--limit N]` | — | Recent feedback rows |

After ≥3 reports per file (scoped per project): **missing** files get
`+0.05`, **noisy** files get `−0.10`, **files_read** files get `+0.03`.
Since v4.4.2, deltas are cosine-weighted by query similarity — feedback
for query X only fires strongly for similar future queries.

### Multi-repo workspaces

| Command | Purpose |
|---|---|
| `workspace init [--name NAME]` | Create `workspace.yaml` at the workspace root |
| `workspace repo add NAME PATH` | Register a repo (captures git branch + SHA) |
| `workspace repo list [--json]` | List registered repos |
| `workspace link add FROM TO` | Declare a dependency (boosts cross-repo confidence) |
| `workspace detect-links` | Auto-detect cross-repo links from Python imports + OpenAPI/protobuf/GraphQL |
| `workspace pack --mode MODE [--query TEXT]` | Unified ranked pack across all workspace repos with `[repo-name]` labels |

When a pack spans repos, edges crossing community boundaries emit a
stderr warning (`workspace_cross_community_threshold` in config, default
50). Tune upward for large codebases.

### Other

| Command | MCP tool | Purpose |
|---|---|---|
| `explain last-pack [--show-call-chains]` | `explain_selection` | Why each item was selected + token stats |
| `graph [--open] [--output PATH]` | — | Interactive D3 HTML graph of the symbol/edge graph |
| `graph call-chain --symbol-id N --max-depth K` | `get_call_chain` | BFS the `calls` edges from a seed symbol |
| `audit --untested-hotspots` | — | Rank high-inbound symbols with zero `tested_by` edges |
| `embed` | — | Pre-compute symbol embeddings (offline; makes `--with-semantic` a cosine lookup) |
| `benchmark run [--task-suite NAME] [--runs N]` | — | Run the benchmark suite (95% CIs at N≥10) |
| `mcp` | — | Start the MCP server over stdio |

### Configuration

`.context-router/config.yaml` — overridable per project:

```yaml
# Per-mode token budget overrides (v4.4 defaults shown)
mode_budgets:
  review: 1500
  implement: 1500
  debug: 2500
  handover: 4000
  minimal: 800

# fnmatch patterns to exclude from indexing
ignore_patterns: [".git", "__pycache__", "*.pyc", ".venv", "node_modules", "dist", "build"]

# Per-mode confidence weights (advanced)
confidence_weights:
  review:
    changed_file: 0.98
    blast_radius: 0.65
  implement:
    entrypoint: 0.95
  debug:
    failing_test: 0.90
  handover:
    memory: 0.85

# Multi-repo: warn when edges cross this many community boundaries
workspace_cross_community_threshold: 50
```

---

## 7. Worked examples

### Example A — bug fix

```bash
# 1. Search memory for past work on this area
context-router pack --mode debug \
  --query "intermittent 500 on /users endpoint after auth refactor" \
  --json | jq '.selected_items[].title'

# 2. Read the top-ranked items the pack returned (your agent does this).
# 3. Make the fix, commit. (The post-commit hook auto-saves an observation.)
# 4. Mid-session: capture the root cause for future agents.
context-router memory capture \
  "/users 500 was caused by stale auth-cache TTL after we removed the warmer; added 60s grace period." \
  --task-type debug \
  --files "src/auth/cache.py tests/test_auth_cache.py" \
  --fix "ttl_grace_seconds=60"

# 5. Close the loop.
context-router feedback record \
  --pack-id "$(jq -r .id .context-router/last-pack.json)" \
  --useful yes \
  --missing src/auth/warmer.py
```

### Example B — feature implementation

```bash
context-router pack --mode implement --with-rerank \
  --query "add per-user rate limiting to the public API"

# Read the pack. If unsure which extension point to hook into:
context-router pack --mode minimal --query "rate limit middleware"

# After implementing:
context-router decisions add "Adopt token-bucket rate limiting" \
  --decision "token-bucket via Redis SETNX + EX, 100 req/min per user" \
  --context "Considered leaky-bucket (more memory) and fixed-window (burst risk)" \
  --status accepted
```

### Example C — handover

```bash
# Compact ranked pack of recent changes + relevant memory + ADRs
context-router pack --mode handover --json > handover.json

# Or: deterministic markdown wiki (no LLM in the loop)
context-router pack --mode handover --wiki --out HANDOVER.md
```

---

## 8. Multi-repo workspaces

context-router can index and pack across N repos at once.

```bash
# In the workspace root (e.g. ~/Documents/my-org/):
context-router workspace init --name my-org
context-router workspace repo add api ./services/api
context-router workspace repo add web ./apps/web
context-router workspace repo add mobile ./apps/mobile

# Auto-detect cross-repo dependencies
context-router workspace detect-links

# Or declare them manually
context-router workspace link add web api
context-router workspace link add mobile api

# Packs now span the workspace with [repo] prefixes
context-router workspace pack --mode review \
  --query "add a user-deletion endpoint and wire it into web + mobile"
```

**Memory and decisions are per-repo by default** (each repo's
`.context-router/memory/` lives inside that repo). To share across the
workspace, commit memory to each repo and rely on `workspace pack`'s
unified ranking.

---

## 9. Troubleshooting

| Symptom | First thing to try |
|---|---|
| MCP tools don't appear in agent | `context-router doctor` — checks `.mcp.json` and PATH |
| "No symbols found" / empty packs | `context-router index` — index may be stale or never built |
| Index is slow / hangs on large repos | Add `node_modules`, `.venv`, `dist` to `ignore_patterns` in `.context-router/config.yaml` |
| Index dropped legitimate files | Check repo size; v4.4.3 fixed a 10K cap that affected very large repos. Run `context-router --version` to confirm ≥4.4.3 |
| `--with-rerank` errors / model download fails | Falls back silently when offline; use `--no-rerank` to force off |
| `--with-semantic` slow on first call | Run `context-router embed` once to pre-compute |
| Hook captures look wrong | `--with-hooks --upgrade` to refresh hook scripts |
| Setup says "already configured, skipped" but I want the new contract | `context-router setup --upgrade` rewrites managed blocks in-place |
| Multi-repo packs miss cross-repo deps | `workspace detect-links` (auto) or `workspace link add FROM TO` (manual) |

If `doctor` doesn't surface the problem, set `CONTEXT_ROUTER_LOG=debug`
and re-run the failing command — verbose stderr will localise the
issue.

---

## 10. Performance expectations

From the v4.4.3 holdout benchmark (18 tasks across 6 OSS projects in
5 languages):

- **Avg pack size:** 159 tokens combined (vs ~1,506 for
  `code-review-graph` — **−89.4% combined, up to −91.2% on Suite B**;
  no recall regression).
- **Rank-1 hit rate:** 17/18 (94%) — top item is the ground-truth file.
- **Avg recall (file-level):** 94% (Suite B: 100%).
- **Latency (typical CLI):** index <30s on most repos; pack <500ms
  cold, <100ms warm (L1 in-process + L2 SQLite cache).

Token reduction vs **naive whole-file context** (legacy benchmark
methodology): 49–99% depending on repo size. Larger repos see higher
reductions because the naive denominator grows faster than pack size.

See [`BENCHMARKS.md`](BENCHMARKS.md) for full results, per-task tables,
and reproduction commands.
