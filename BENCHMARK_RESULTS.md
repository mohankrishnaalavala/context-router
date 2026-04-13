# context-router Benchmark Results

Measured against the **context-router repository itself** (104 files, 1,189 symbols)
using the built-in 20-task suite (5 tasks × 4 modes).

**Run date:** 2026-04-12  
**Run ID:** `5b4a6d00`  
**Token budget:** 8,000 (default)

---

## TL;DR

| Metric | Value |
|--------|-------|
| Tasks run | 20 / 20 |
| Success rate | **100%** |
| Average token reduction | **64.7%** |
| Average tokens selected | **8,000** |
| Average latency | **131 ms** |

---

## Baseline Comparison

| Approach | Tokens | vs Router |
|----------|--------|-----------|
| Naive (all 1,189 symbols) | 22,661 | 2.8× more |
| Keyword match (top 50 symbols) | 1,221 | fewer but less relevant |
| **context-router** | **8,000** | **—** |

**Key insight**: Naive feeding of the entire codebase uses **2.8× more tokens**
than the context-router budget. The router selects the most structurally
relevant items within the budget rather than blindly truncating.

---

## Results by Mode

### Review (5/5 succeeded)

Average reduction: **64.7%** | Avg tokens: **8,000** | Avg latency: **211 ms**

| ID | Query | Tokens | Reduction | Latency |
|----|-------|--------|-----------|---------|
| ✅ rev-01 | review recent authentication changes for security issues | 8,000 | 65% | 205 ms |
| ✅ rev-02 | check for breaking API changes and backwards compatibility | 8,000 | 65% | 178 ms |
| ✅ rev-03 | security audit of input validation and SQL injection risks | 8,000 | 65% | 285 ms |
| ✅ rev-04 | review database migration scripts for data loss risks | 8,000 | 65% | 197 ms |
| ✅ rev-05 | review dependency upgrades for breaking changes and CVEs | 8,000 | 65% | 189 ms |

### Implement (5/5 succeeded)

Average reduction: **64.7%** | Avg tokens: **8,000** | Avg latency: **94 ms**

| ID | Query | Tokens | Reduction | Latency |
|----|-------|--------|-----------|---------|
| ✅ imp-01 | add an in-memory caching layer for expensive database queries | 8,000 | 65% | 78 ms |
| ✅ imp-02 | implement request rate limiting per user and per IP | 8,000 | 65% | 77 ms |
| ✅ imp-03 | add cursor-based pagination to list endpoints | 8,000 | 65% | 156 ms |
| ✅ imp-04 | create a new REST API endpoint for user preferences | 8,000 | 65% | 86 ms |
| ✅ imp-05 | add structured JSON logging with trace IDs and request context | 8,000 | 65% | 72 ms |

### Debug (5/5 succeeded)

Average reduction: **64.7%** | Avg tokens: **8,000** | Avg latency: **111 ms**

| ID | Query | Tokens | Reduction | Latency |
|----|-------|--------|-----------|---------|
| ✅ dbg-01 | NullPointerException thrown in the service layer during startup | 8,000 | 65% | 115 ms |
| ✅ dbg-02 | test suite failures after database schema migration | 8,000 | 65% | 113 ms |
| ✅ dbg-03 | performance regression — API response times doubled after last deploy | 8,000 | 65% | 106 ms |
| ✅ dbg-04 | memory leak causing OOM errors in the worker process after 24 hours | 8,000 | 65% | 117 ms |
| ✅ dbg-05 | intermittent CI failure in integration tests — passes locally | 8,000 | 65% | 105 ms |

### Handover (5/5 succeeded)

Average reduction: **64.7%** | Avg tokens: **8,000** | Avg latency: **109 ms**

| ID | Query | Tokens | Reduction | Latency |
|----|-------|--------|-----------|---------|
| ✅ hov-01 | hand off the in-progress authentication refactor to a new engineer | 8,000 | 65% | 142 ms |
| ✅ hov-02 | document the storage layer refactor completed this sprint | 8,000 | 65% | 92 ms |
| ✅ hov-03 | summarise all work completed this sprint for the team retrospective | 8,000 | 65% | 112 ms |
| ✅ hov-04 | onboard a new engineer to the API gateway service | 8,000 | 65% | 105 ms |
| ✅ hov-05 | capture key architectural decisions made during the database migration | 8,000 | 65% | 96 ms |

---

## External Repo Testing (Phase 4–6 E2E)

### project_handover (Python CLI tool)

**Repo stats:** 138 files · 1,313 symbols · 1,840 edges · Python + TypeScript/JS  
**Init + index time:** ~1.5 s  
**Token budget:** 8,000 (default)  
**Run date:** 2026-04-13

| Mode | Query | Tokens used / total | Reduction | Latency |
|------|-------|---------------------|-----------|---------|
| review | review the handover generation pipeline | 8,000 / 38,319 | **79.1%** | ~860 ms |
| implement | add support for Notion export format | 7,998 / 38,319 | **79.1%** | ~710 ms |
| handover | _(no query)_ | 8,000 / 38,319 | **79.1%** | ~680 ms |
| debug | AttributeError in LLM client (with error-file) | 8,180 / 38,430 | **78.7%** | ~850 ms |

**Token comparison vs naive (all 1,313 symbols):**  
Naive ≈ 38,319 tokens · Router selects 8,000 → **79% reduction**, 4.8× more efficient.

#### Debug mode highlights

- **runtime_signal** items (0.95 confidence) surfaced `sync.py`, `_decide_with_llm`, `sync_backlog` directly from the stack trace
- **failing_test** items (0.95/0.85) surfaced test functions matching the affected class
- Memory capture + FTS search round-trip working: captured observation found immediately via `memory search "LLM client"`
- `memory export` produced shareable Markdown in < 100 ms
- `decisions export` produced ADR file `0001-use-json-for-handover-conversation-storage.md` correctly

#### Feedback loop testing

```
context-router feedback record --pack-id test-pack-001 --useful yes --missing "handover/llm.py"
context-router feedback record --pack-id test-pack-002 --useful no --noisy "dist/extension/background.js"
context-router feedback stats
# Total feedback: 2 | Useful: 1 Not useful: 1 (50.0%)
# Top missing: handover/llm.py
# Top noisy: dist/extension/background.js
```

Feedback aggregation, missing-file tracking, and noisy-file tracking all work as designed.

---

### handover_website (Astro/TypeScript site)

**Repo stats:** 26 files · 549 symbols (after excluding node_modules) · TypeScript/JS only  
**Note:** Primary source files are `.astro` components — context-router does not yet have an Astro language analyzer. Only `.js` config files in `node_modules/.vite/` were indexed.  
**Limitation documented:** Astro/Vue/Svelte single-file component support is a future extension point.

---

### Multi-repo workspace (project_handover + handover_website)

```bash
context-router workspace init --root ./workspace --name "handover-projects"
context-router workspace repo add project-handover /path/to/project_handover --language python
context-router workspace repo add handover-website /path/to/handover_website --language typescript
context-router workspace pack --mode review --query "review handover generation pipeline"
# ~7,999 tokens  (79% reduction)  |  latency ~930 ms
```

Cross-repo pack shows `[project-handover]`-prefixed items, unified token budget, latency overhead ~70 ms vs single-repo.

---

## Phase 4–6 Feature Effectiveness

### Freshness scoring (Phase 2)

Observations decay with a 30-day half-life. Fresh observations (< 1 day) at effective confidence 0.498; 30-day-old observations drop to 0.25. Access boost (+0.02 per access, cap 0.20) rewards frequently-recalled facts.

### error_hash recall (Phase 4)

Same error seen across multiple debug sessions produces a stable 16-char hash (e.g. `b30f6a3f...`). Files from prior stack traces are stored in `runtime_signals.top_frames` and recalled as `past_debug` (confidence 0.90) when the hash recurs — surfacing files from the *fix* that weren't in the current stack trace.

### Agent feedback loop (Phase 6)

After ≥3 feedback reports marking a file as missing/noisy, the orchestrator applies confidence adjustments automatically:
- missing files: **+0.05** boost
- noisy files: **−0.10** penalty

This makes context packs self-improving over team usage without any manual configuration.

---

## How to Reproduce

```bash
# Initialise and index the project
uv run context-router init
uv run context-router index

# Run the 20-task benchmark suite
uv run context-router benchmark run

# Print the Markdown report
uv run context-router benchmark report
```

To adjust the token budget (default 8,000), edit `.context-router/config.yaml`:

```yaml
token_budget: 16000
```

---

## Notes on Methodology

- **Token estimation**: `max(1, len(text) // 4)` (character-based, no tokenizer dependency).
- **Naive baseline**: sum of all indexed symbol signatures + docstrings with no filtering.
- **Keyword baseline**: substring match in symbol name/signature/docstring, top 50 results.
- **Router output**: confidence-ranked symbols within the 8,000-token budget (≥1 item per source type preserved).
- **Latency** includes uv process startup (~500 ms cold); warm invocations are ~150–200 ms.
- All tasks hit the token budget cap (8,000 tokens) because the codebase is large enough — the ranking still selects the *highest-confidence* items within that budget, not random ones.

_Generated by [context-router](https://github.com/mohankrishnaalavala/context-router) v0.2.2_
