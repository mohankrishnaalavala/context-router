# context-router Roadmap

> **Current version:** 0.2.2  
> **Benchmark baseline:** 64.7 % average token reduction · 131 ms average latency

---

## Phase 1 — Automatic Memory Capture *(this release)*

**Goal:** Close the biggest gap today — memory exists but writes are still manual.

### Write-side API

| Addition | Description |
|---|---|
| `memory add --stdin` | Read session JSON from stdin — enables pipe-based capture (`echo '…' \| context-router memory add --stdin`) |
| `memory capture SUMMARY` | Direct structured capture from CLI args — no JSON file needed |
| MCP `save_observation` | Write-capable MCP tool so agents can persist learning, not just read it |
| MCP `save_decision` | Write-capable MCP tool for architectural decision records |

### Auto-save Hooks

| Hook | Trigger | What is saved |
|---|---|---|
| Agent completion | `scripts/hooks/on_agent_complete.py` | task type, summary, files touched, commands, fix summary, commit SHA |
| Git commit | `.githooks/post-commit` | commit message, changed files, commit SHA |
| Debug resolve | `scripts/hooks/on_debug_resolve.py` | error description, fix, affected files |
| Handover | `scripts/hooks/on_handover.py` | session summary, files, commit |

### Guardrails

- **Deduplication** — short SHA256 hash of `(task_type, summary)` prevents duplicate observations for the same task.
- **Secret redaction** — credential patterns (`TOKEN=…`, `Bearer …`, `api_key=…`) are redacted from `commands_run` before storage.
- **File threshold** — git commit hook skips if zero files changed; `memory capture` accepts `min_files=0` for hooks where file count is not meaningful.
- **One summary per task** — `capture_observation` in `packages/memory/src/memory/capture.py` enforces all guardrails before any INSERT.

---

## Phase 2 — Memory Freshness + Dedupe Scoring

**Goal:** Keep memory useful as the codebase evolves.

- **Confidence decay** — observations age: confidence decreases over time (configurable half-life).
- **Superseded linking** — when a new observation covers the same area, the old one is marked `superseded` rather than deleted.
- **Duplicate merge** — near-duplicate observations (Jaccard similarity > threshold) are merged into the highest-confidence record.
- **ADR status tracking** — decisions can be marked `deprecated` or linked to a replacement via `superseded_by`.

---

## Phase 3 — Stronger Java, .NET, and YAML Analyzers

**Goal:** Make context packs useful for enterprise mono-repos, not just Python projects.

| Language | Current state | Target |
|---|---|---|
| Python | Full Tree-sitter (classes, functions, imports, calls) | Done |
| TypeScript/JS | Full Tree-sitter | Done |
| Java | Stub — extracts class/method names | Full: generics, annotations, Maven/Gradle dependencies |
| .NET / C# | Stub — extracts namespace/class/method | Full: using directives, attributes, NuGet deps |
| YAML | Stub — key extraction | Full: Kubernetes, Helm, GitHub Actions semantic awareness |

---

## Phase 4 — Better Debug Memory

**Goal:** Make debug-mode retrieval precise rather than keyword-based.

Store richer debug signals:

- **Error signature hash** — normalized hash of the exception type + message (without line numbers) for exact-match retrieval.
- **Top stack frames** — top 5 frame file+function pairs for structural similarity matching.
- **Failing test names** — extracted from JUnit XML or pytest output.
- **Config/environment hints** — Python version, key env vars, OS (redacted).
- **Fix commit SHA** — links the observation to the exact commit that resolved the issue.

---

## Phase 5 — Shared / Team-Safe Export

**Goal:** Enable collaboration without forcing teams to commit the SQLite database.

- `context-router memory export` — exports selected observations as a Markdown handover document.
- `context-router decisions export` — exports accepted decisions as individual ADR Markdown files (`docs/adr/`).
- `--redacted` flag — strips file paths and command details; safe for sharing in public repos.
- Optional `.context-router/export/` drop directory so CI can publish exports as build artifacts.

---

## Phase 6 — Agent Feedback Loop

**Goal:** Improve pack ranking from real usage signal rather than heuristics alone.

After an agent consumes a context pack it can report back:

```
context-router feedback --pack-id PACK_ID --useful yes --missing "auth.py"
context-router feedback --pack-id PACK_ID --useful no --reason "too much context"
```

Feedback fields:

| Field | Values |
|---|---|
| `useful` | `yes` / `no` |
| `missing` | File or symbol that should have been included |
| `noisy` | File or symbol that should have been excluded |
| `too_much_context` | Boolean |

Feedback is stored and used to adjust per-source-type confidence weights and keyword boost factors over time.

---

## Non-Goals (by design)

- **No remote database** — context-router is local-first; all data stays in `.context-router/context-router.db`.
- **No cloud sync** — use `memory export` + your own version control for team sharing.
- **No LLM summarization** — summaries are authored by the agent or developer, not generated. This keeps the tool deterministic and free to run.
