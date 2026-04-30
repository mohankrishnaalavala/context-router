# AGENTS.md — context-router

This repo dogfoods its own tool. AI coding agents working here MUST follow the bootstrap contract:

**→ Read [`.handover/prompts/agent-bootstrap.md`](.handover/prompts/agent-bootstrap.md) before doing anything else.**

That file is the single source of truth for:

- Required start-of-session calls (`search_memory`, `get_context_pack`)
- Required end-of-session call (`save_observation`)
- How to keep the index live (`context-router watch`)
- When to call `save_decision` for architectural decisions
- Repo conventions (branching, commits, tests, lint)

For repo-specific quality rules and the design / decision pipeline, also read [`CLAUDE.md`](CLAUDE.md).

---

**TL;DR for any agent landing here cold:**

```bash
# 1. In a terminal:
context-router watch &

# 2. In your agent session:
#    First call:  search_memory(query="<task>")
#    Second call: get_context_pack(mode="handover")
#    Last call:   save_observation(summary="...", task_type="...", files_touched=[...])
```

No other knowledge-graph tools are wired into this repo. Do not introduce `code-review-graph`, `aider-repomap`, or similar — context-router is the local stack.
