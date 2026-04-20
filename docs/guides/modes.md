# Which `--mode` should I use?

`context-router pack` and `get_context_pack` (MCP) accept five modes. Each mode
is a different ranking + filtering strategy tuned to one kind of task. Picking
the wrong mode still works — you just get lower‑signal output.

## 30‑second decision tree

```
Start here.
│
├── Are you starting from a failing test / traceback / error log?  ──▶  debug
│
├── Have you already started writing code and want to review?      ──▶  review
│
├── Are you resuming a session / onboarding / writing a handover?  ──▶  handover
│
├── Do you want the 3–5 most relevant files only (cheap triage)?   ──▶  minimal
│
└── Everything else — writing a new feature / fixing a bug          ──▶  implement
```

## "I am trying to…" → mode

| You are trying to | Use this mode |
|---|---|
| Add a new feature | `implement` |
| Fix a bug from a description (no diff yet) | `implement` |
| Fix a bug from a stack trace or failing test | `debug` |
| Explain what changed in a PR | `review` |
| Risk‑assess a diff before merging | `review` |
| Jump into a new codebase cold | `handover` |
| Resume after a compaction / new session | `handover` |
| Write a one‑screen status brief | `handover` |
| Get the 3–5 most relevant files fast, then iterate | `minimal` |
| Pre‑screen before paying for a full pack | `minimal` |

## Mode reference

### `review`

Ranks changed files plus their callers, tests, and direct dependents. Risk‑
scored when a diff is present. Expect an opinion‑shaped output, not raw
retrieval. Use `--pre-fix` to get a review pack **before** the diff lands
(useful for planning). Review is the only mode that currently defaults to
`--top-k 5 --max-tokens 4000` in v3.3.0 — see β2 in the v3.3.0 spec for why.

### `implement`

Ranks by relevance to a free‑text description. Pulls in definitions, close
neighbours, and exemplar tests. Broader than `review` — it is *retrieval*, not
*triage*. Use this when you know what you want to build but not which files
to touch.

### `debug`

Starts from the failure signal (stack trace, test name, error file via
`--error-file`), walks the call graph backward, and prioritises runtime
evidence when available. Does not dedup as aggressively as `review` because
repeated symbols in a trace are diagnostically useful.

### `handover`

Optimises for *breadth over depth*. Emits a map of the project's major
surfaces (entry points, public APIs, key configs) plus the current session's
focus files. Use this to bootstrap a new session or to hand a task off to
another agent. Prose‑oriented; the `--format agent` flag (v3.3.0) will warn
you that output may be low‑signal here.

### `minimal`

Reuses `implement` candidate selection then caps to top 5 with a
`next_tool_suggestion` for follow‑up. Cheapest mode. Use when you want to
spend ~500 tokens confirming which files to open before running a full
`implement` pack.

## Which flags interact with which modes?

| Flag | `review` | `implement` | `debug` | `handover` | `minimal` |
|---|---|---|---|---|---|
| `--top-k` | ✓ default 5 | ✓ | ✓ | ✓ | capped at 5 |
| `--max-tokens` | ✓ default 4000 | ✓ | ✓ | ✓ | ✓ |
| `--pre-fix` | ✓ | no‑op (warns) | no‑op (warns) | no‑op (warns) | no‑op (warns) |
| `--error-file` | no‑op | no‑op | ✓ | no‑op | no‑op |
| `--format agent` | ✓ | ✓ | ✓ | ⚠ warns | ✓ |
| `--format json` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `--with-semantic` | ✓ | ✓ | ✓ | ✓ | ✓ |

Rows marked "no‑op (warns)" mean the flag has no effect but context‑router
prints a note to stderr explaining why — there are no silent no‑ops (project
rule).

## Common pitfalls

- **"I used `implement` for a PR review and it was verbose."** Try `review`
  — it narrows to the diff's blast radius.
- **"`handover` doesn't find the files I just edited."** Handover ranks for
  breadth; your recent edits are already in session state. If you want
  *deep* recency, use `implement` with the task description.
- **"`debug` returned random stuff."** `debug` needs a failure signal.
  Without `--error-file` or a traceback in the query, it falls back to
  keyword retrieval.
- **"Pack is too big."** That's not a mode problem — set `--max-tokens` or
  `token_budget` in `config.yaml`. v3.3.0 honours both; older versions silently
  ignored `token_budget`.
