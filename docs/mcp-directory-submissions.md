# MCP Directory Submission Drafts

Ready-to-paste PR content for submitting context-router to MCP server directories.
Submit these PRs manually after the v0.3.0 release is live on PyPI.

---

## punkpeye/awesome-mcp-servers

**PR title:** `Add context-router — minimum-context selector for AI coding agents`

**File to edit:** `README.md`

Find the section for developer tools / code editors (or a relevant "utilities" section) and add:

```markdown
- [context-router](https://github.com/mohankrishnaalavala/context-router) - Local-first context selector for AI coding agents. Indexes code structure, runtime evidence, and project memory into SQLite; ranks and serves minimum-token context packs (64–80% reduction) for review, debug, implement, and handover tasks. 13 MCP tools, Python/TypeScript/Java/.NET support, no API key required.
```

---

## appcypher/awesome-mcp-servers

**PR title:** `Add context-router — token-efficient context selection for AI coding agents`

**File to edit:** `README.md`

Find the developer tools / code intelligence section and add:

```markdown
### context-router

A local-first MCP server and CLI that selects the **minimum useful context** for AI coding agents.

- Indexes symbols, call graphs, dependency edges, and test coverage into a local SQLite database
- Ranks by structural relevance, query similarity, and task mode (review/debug/implement/handover)
- Enforces a token budget — 64–80% average reduction on real-world Python repos
- 13 MCP tools compatible with Claude Code, Cursor, Windsurf
- No API key required

**Install:** `pip install context-router-cli` or `uv tool install context-router-cli`  
**Repo:** https://github.com/mohankrishnaalavala/context-router  
**PyPI:** https://pypi.org/project/context-router-cli/
```

---

## Notes

- Wait until the PyPI release (`v0.3.0`) is visible at https://pypi.org/project/context-router-cli/ before submitting
- Check the target repo's CONTRIBUTING guide for any formatting requirements
- Both repos may ask for the entry in alphabetical order within their section
