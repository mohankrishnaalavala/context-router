# Risks & Open Questions
<!-- Last updated: 2026-04-24 · Updated for v4.2 state -->

---

## Open Questions

- **Staleness thresholds for v4.3:** What is the right age cutoff for `old_commit` severity — 30 days? 90 days? Should it be configurable?
- **Federation consistency:** When workspace repos are on different branches, federated memory hits may reference code that doesn't exist in the querying repo. Should hits from out-of-sync repos be suppressed or labeled?
- **Memory quality drift over time:** As observation counts grow, BM25+recency scoring may surface old, low-relevance hits. When does a corpus need pruning beyond just stale-file removal?
- **SSE transport scope:** Should the MCP server support SSE transport for remote/cloud Copilot agents in v4.x or defer to a separate adapter?
- **Token estimator accuracy:** Character/line heuristics produce approximate estimates. At what point does estimation error meaningfully affect pack quality decisions?

---

## Active Risks

- **Observation quality at scale:** As teams accumulate hundreds of observations, the write gate (60-char summary, non-empty files_touched) may not be sufficient to prevent low-signal entries from degrading BM25 results. A quality score at write time is a post-v4.3 backlog item.
- **Adaptive top-k calibration:** The 0.6 confidence threshold was tuned on the judge benchmark fixture. It may need per-mode tuning as new language analyzers produce different confidence distributions.
- **Cross-repo memory federation false positives:** Federated hits from sibling repos may reference symbols that don't exist in the querying repo's context. Precision of federated search is untested at scale.
- **Stale index warning reliability:** Comparing index mtime to `git log` timestamp is heuristic. A repo with frequent amend-commits or rebases may produce spurious warnings.
- **Tree-sitter grammar coverage:** Not all Java, .NET, or YAML constructs are covered in current grammars; some symbol extraction remains incomplete in edge cases.
- **Watchdog reliability on Linux:** Event-driven file watching behaves differently across OS platforms; incremental indexing may miss events on some Linux configurations.
- **Copilot custom agent file format stability:** The `.github/agents/*.md` format is relatively new and may change; adapter output should remain versioned.

---

## Resolved Risks (archived)

- ~~**Ranking cold start:** Without runtime signals or memory, packs are graph-only and may not beat baselines.~~ → Resolved: memory injection (v4.1), adaptive top-k (v4.2), and the eval harness CI gate (v4.0) together ensure measurable quality above baseline.
- ~~**Fresh-install indexing zero files:**~~ → Resolved in v3.3.0 via entry-point registration and `context-router doctor`.
- ~~**Default pack size (50k+ tokens):**~~ → Resolved in v3.3.0 via `--mode review` sane defaults (top-k 5, max-tokens 4000).
- ~~**`<external>` placeholder items in packs:**~~ → Resolved in v3.3.0; unresolved entries are dropped with count surfaced on `pack.metadata.external_dropped`.
- ~~**MCP server crash on fresh pip install:**~~ → Resolved in v3.3.1 hotfix; version fallback to `context-router-cli` distribution.
- ~~**Staged observations incorrectly classified as committed:**~~ → Resolved in v4.2 provenance implementation.
