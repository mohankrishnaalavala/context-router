---
id: 2026-06-10-v46-hands-free-context-roadmap-plan-w
type: observation
task: handover
files_touched:
  - docs/superpowers/plans/2026-06-10-v4.6-roadmap.md
created_at: 2026-06-10T22:32:33.456075+00:00
author: context-router
---

v4.6 "Hands-Free Context" roadmap plan written: graph accuracy fixes first (edge dedup, symbol qualification, count consistency, get_all paging, ground-truth audit), then pack-time staleness self-heal + hooks installer, auto-capture observations at SessionEnd + doctor memory health, and a localhost savings dashboard (pack_events telemetry + stdlib http.server). Multi-repo explicitly deferred.

Plan at docs/superpowers/plans/2026-06-10-v4.6-roadmap.md. Key code anchors found during exploration: EdgeRepository.add_bulk repositories.py:927 (no unique constraint on edges), get_all 10k cap repositories.py:538 with 4 orchestrator callers (1668/1696/2315/2743), watcher debounce watcher.py:27, MCP server has no shutdown handler so auto-save must ride Claude Code SessionEnd hooks, CLI has zero HTTP deps so dashboard uses stdlib http.server. Sequencing A→B→C→D; optional split v4.6=A+B, v4.7=C+D. Plan not yet committed — awaiting user scope approval, then design specs in docs/design/v4.6-*.md + DoD entries before code.
