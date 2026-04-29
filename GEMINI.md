# GEMINI.md — context-router

This repo dogfoods its own tool. Gemini CLI sessions working here MUST follow the bootstrap contract:

**→ Read [`.handover/prompts/agent-bootstrap.md`](.handover/prompts/agent-bootstrap.md) before doing anything else.**

That file is the single source of truth for:

- Required start-of-session calls (`search_memory`, `get_context_pack`)
- Required end-of-session call (`save_observation`)
- How to keep the index live (`context-router watch`)
- When to call `save_decision` for architectural decisions
- Repo conventions (branching, commits, tests, lint)

For repo-specific quality rules and the design / decision pipeline, also read [`CLAUDE.md`](CLAUDE.md).

---

**Gemini CLI MCP setup** — `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "context-router": { "command": "context-router", "args": ["mcp"] }
  }
}
```

The repo's `.mcp.json` already points at the right server; agents launched from this directory inherit the config.

No other knowledge-graph tools are wired into this repo. Do not introduce `code-review-graph`, `aider-repomap`, or similar — context-router is the local stack.
