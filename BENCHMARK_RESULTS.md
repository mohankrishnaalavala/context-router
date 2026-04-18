# context-router Benchmark Results

Real-world measurements, updated per release. Numbers tagged by release.

---

## v3.1 — keyword-baseline honesty fix

v3.1 ships the fix for the v3.0.0 `vs_keyword` clamp described under
"Honesty caveat" in the historical v3.0.0 notes (now removed from that
section because the bug is fixed). The Markdown baseline-comparison
table and the new per-task `vs_keyword` JSON field are now signed —
negative values surface honestly where the keyword baseline pack is
tighter than the router pack. Registry outcome:
[`benchmark-keyword-baseline-honest`](docs/release/v3-outcomes.yaml).

The per-task fields `vs_keyword`, `vs_naive`, `keyword_baseline_tokens`,
and `naive_baseline_tokens` now appear on every `TaskMetrics` entry in
the JSON report for programmatic consumers.

---

## v3.0.0 — 2026-04-18

Token budget: 8,000 (default). Runs: 10 per task. Latency measured warm (after L2 cache fill). `--runs 10` produces non-null 95% CIs on every metric.

### TL;DR (v3.0.0 — across 3 real OSS repos + self)

| Repo | Files | Symbols | Task suite | Mean reduction | Latency (warm) | Tasks OK |
|---|---|---|---|---|---|---|
| context-router (self) | 426 | 1,768 | generic | **94.85%** (CI 94.84–94.86) | 5.84 ms (CI 5.52–6.15) | 20 / 20 |
| bulletproof-react | 426 | 769 | typescript | **78.69%** (CI 78.69–78.70) | 5.77 ms (CI 5.49–6.05) | 15 / 15 |
| eShopOnWeb | 352 | 1,386 | dotnet | **90.40%** (CI 90.39–90.41) | 5.77 ms (CI 5.49–6.05) | 15 / 15 |
| spring-petclinic | 48 | 217 | java | **52.63%** (CI 52.41–52.85) | 5.53 ms (CI 5.24–5.82) | 15 / 15 |

Methodology: `uv run context-router benchmark run --project-root <repo> --task-suite <suite> --runs 10 --json`. CI = mean ± 1.96·σ/√n.

### v3.0.0 delta vs v2.0.0 (where comparable)

- **Cold pack-build wall time: 35–49 % faster** across all three fixtures (0.79 s / 0.89 s / 0.71 s on bulletproof-react / eShopOnWeb / spring-petclinic, median of 3 cold runs).
- **Warm pack-build inner pipeline (SQLite L2 cache): 3.7× to 12× faster** on repeat queries.
- **15 / 15 task-suite success rate** on each of the three external repos.

### Cold-vs-warm pipeline latency (v3.0.0)

| Repo | Cold build (inner) | Warm build (inner) | Speedup |
|---|---|---|---|
| bulletproof-react | 195 ms | 23 ms | **8.5×** |
| eShopOnWeb | 229 ms | 19 ms | **12×** |
| spring-petclinic | 81 ms | 22 ms | **3.7×** |

End-to-end CLI wall time (including uv/typer/rich startup ~0.55 s) is dampened by startup, which is why the public number is "35–49 % faster" rather than "10× faster."

### Graph-edge accuracy (v3.0.0)

| Repo | `calls` | `extends` | `implements` | `tested_by` | `imports` |
|---|---|---|---|---|---|
| bulletproof-react | 240 | 0 | 0 | 0 | 0 |
| eShopOnWeb | 348 | 126 | 44 | 41 | 32 |
| spring-petclinic | 243 | 11 | 6 | 38 | 29 |

bulletproof-react's zeros are a known v3.1 follow-up (TypeScript analyzer extends inheritance/tested_by extraction to function-component + JSX patterns). Zero constructor-anchored inheritance edges on eShopOnWeb confirms the #60 analyzer fix landed cleanly (was 90 pre-#60).

---

## v0.6 / historical — 2026-04-13

Real-world measurements on external Python codebases (pre-CRG-parity, pre-cache persistence).
Retained for trend tracking.

### Legacy TL;DR

| Repo | Files | Symbols | Avg Reduction | Hit Rate vs Random | Latency |
|------|-------|---------|---------------|--------------------|---------|
| project_handover (Python CLI) | 138 | 1,313 | **79.1%** | — | ~750 ms |
| secret-scan-360 (security scanner) | 183 | 543 | **49.4%** | **48.1% vs 35.2%** | 105 ms |
| context-router (self) | 190 | 1,100 | **80.9%** | 37.2% vs 41.2% | 333 ms |

> **Quality note:** Hit rate measures what fraction of "expected relevant symbols" the router
> selected. Router outperforms random baseline by **+12.9 pp** on secret-scan-360 (domain match).
> Self-benchmark hit rate is below random — expected, since generic task queries (auth, rate
> limiting) don't match context-router's internal symbol names.

---

## External Repo: secret-scan-360 (Python security scanner)

**Repo stats:** 183 files · 543 symbols · Python  
**Token budget:** 8,000 (default)  
**Run date:** 2026-04-13  
**Run ID:** `5e7e68c9`

### Overall Summary

| Metric | Value |
|--------|-------|
| Average token reduction | **49.4%** |
| Average tokens selected | 5,200 |
| Naive baseline (all symbols) | 10,280 |
| Average latency | 105 ms |
| **Hit rate (router)** | **48.1%** |
| Hit rate (random baseline) | 35.2% |
| Rank quality (conf ≥ 0.70) | **75.5%** |

The router selects at **~2× better** hit rate than random sampling for domain-matched tasks.
75.5% of selected items have confidence ≥ 0.70, indicating strong signal from structural sources.

### Results by Mode

#### Review (5/5 succeeded)

Reduction: **49.4%** | Tokens: **5,200** | Latency: **135 ms** | Hit rate: **40.0%** vs 46.6% random

| ID | Query | Tokens | Reduction | Hit Rate | Latency |
|----|-------|--------|-----------|----------|---------|
| ✅ rev-01 | review recent authentication changes for security issues | 5,168 | 50% | 100% | 180 ms |
| ✅ rev-02 | check for breaking API changes and backwards compatibility | 5,220 | 49% | 33% | 114 ms |
| ✅ rev-03 | security audit of input validation and SQL injection risks | 5,184 | 50% | 33% | 113 ms |
| ✅ rev-04 | review database migration scripts for data loss risks | 5,245 | 49% | 33% | 147 ms |
| ✅ rev-05 | review dependency upgrades for breaking changes and CVEs | 5,181 | 50% | 0% | 121 ms |

#### Implement (5/5 succeeded)

Reduction: **50.0%** | Tokens: **5,139** | Latency: **84 ms** | Hit rate: **53.3%** vs 26.7% random

| ID | Query | Tokens | Reduction | Hit Rate | Latency |
|----|-------|--------|-----------|----------|---------|
| ✅ imp-01 | add an in-memory caching layer for expensive database queries | 5,140 | 50% | 33% | 60 ms |
| ✅ imp-02 | implement request rate limiting per user and per IP | 5,139 | 50% | 100% | 59 ms |
| ✅ imp-03 | add cursor-based pagination to list endpoints | 5,138 | 50% | 33% | 155 ms |
| ✅ imp-04 | create a new REST API endpoint for user preferences | 5,139 | 50% | 33% | 75 ms |
| ✅ imp-05 | add structured JSON logging with trace IDs and request context | 5,140 | 50% | 67% | 73 ms |

#### Debug (5/5 succeeded)

Reduction: **49.3%** | Tokens: **5,215** | Latency: **95 ms** | Hit rate: **53.3%** vs 33.3% random

| ID | Query | Tokens | Reduction | Hit Rate | Latency |
|----|-------|--------|-----------|----------|---------|
| ✅ dbg-01 | NullPointerException thrown in the service layer during startup | 5,294 | 48% | 67% | 95 ms |
| ✅ dbg-02 | test suite failures after database schema migration | 5,205 | 49% | 67% | 92 ms |
| ✅ dbg-03 | performance regression — API response times doubled after last deploy | 5,191 | 50% | 33% | 94 ms |
| ✅ dbg-04 | memory leak causing OOM errors in the worker process after 24 hours | 5,191 | 50% | 33% | 89 ms |
| ✅ dbg-05 | intermittent CI failure in integration tests — passes locally | 5,195 | 50% | 67% | 104 ms |

#### Handover (5/5 succeeded)

Reduction: **49.0%** | Tokens: **5,245** | Latency: **104 ms** | Hit rate: **44.4%** vs 33.3% random

| ID | Query | Tokens | Reduction | Hit Rate | Latency |
|----|-------|--------|-----------|----------|---------|
| ✅ hov-01 | hand off the in-progress authentication refactor to a new engineer | 5,216 | 49% | 33% | 94 ms |
| ✅ hov-02 | document the storage layer refactor completed this sprint | 5,274 | 49% | 67% | 98 ms |
| ✅ hov-03 | summarise all work completed this sprint for the team retrospective | 5,225 | 49% | 33% | 97 ms |
| ✅ hov-04 | onboard a new engineer to the API gateway service | 5,220 | 49% | — | 137 ms |
| ✅ hov-05 | capture key architectural decisions made during the database migration | 5,292 | 48% | — | 96 ms |

---

## External Repo: project_handover (Python CLI tool)

**Repo stats:** 138 files · 1,313 symbols · 1,840 edges · Python + TypeScript/JS  
**Token budget:** 8,000 (default)  
**Run date:** 2026-04-13  
**Init + index time:** ~1.5 s

| Mode | Query | Tokens / Total | Reduction | Latency |
|------|-------|----------------|-----------|---------|
| review | review the handover generation pipeline | 8,000 / 38,319 | **79.1%** | ~860 ms |
| implement | add support for Notion export format | 7,998 / 38,319 | **79.1%** | ~710 ms |
| handover | _(no query)_ | 8,000 / 38,319 | **79.1%** | ~680 ms |
| debug | AttributeError in LLM client (with error-file) | 8,180 / 38,430 | **78.7%** | ~850 ms |

**Naive (all 1,313 symbols):** ~38,319 tokens · Router selects 8,000 → **79% reduction, 4.8× more efficient.**

### Debug mode highlights

- `runtime_signal` items (0.95 confidence) surfaced `sync.py`, `_decide_with_llm`, `sync_backlog` directly from the stack trace
- `failing_test` items surfaced test functions matching the affected class
- Memory capture + FTS search round-trip: captured observation found immediately via `memory search "LLM client"`
- `memory export` and `decisions export` both under 100 ms

---

## Phase 4–6 Feature Effectiveness

### Freshness scoring (Phase 2)

Observations decay with a 30-day half-life. Fresh observations (< 1 day) at effective confidence 0.498;
30-day-old observations drop to 0.25. Access boost (+0.02 per access, cap 0.20) rewards
frequently-recalled facts.

### error_hash recall (Phase 4)

Same error seen across multiple debug sessions produces a stable 16-char hash. Files from prior
stack traces are stored in `runtime_signals.top_frames` and recalled as `past_debug` (confidence
0.90) when the hash recurs — surfacing files from the *fix* that weren't in the current stack trace.

### Agent feedback loop (Phase 6)

After ≥3 feedback reports marking a file as missing/noisy, the orchestrator applies confidence
adjustments automatically:
- missing files: **+0.05** boost
- noisy files: **−0.10** penalty

This makes context packs self-improving over team usage without any manual configuration.

---

## Metric Definitions

| Metric | What it measures | Formula |
|--------|-----------------|---------|
| **Token reduction** | How much smaller the context pack is vs the naive "all symbols" baseline | `(baseline_tokens − selected_tokens) / baseline_tokens × 100` |
| **Hit rate (router)** | Fraction of "expected relevant symbols" that appear in the selected pack titles | `# expected_symbols found in pack / total expected_symbols` |
| **Hit rate (random)** | Same metric for a random sample of the same size — the no-skill baseline | Same formula, on a random symbol sample |
| **Rank quality** | Fraction of selected items whose confidence score is ≥ 0.70 — proxy for signal strength | `# high-conf items / total selected items` |
| **Latency** | End-to-end time from query to pack (ms) — includes DB lookup, scoring, ranking | Measured with `time.perf_counter()` |

### Confidence score sources

Items are tagged with a `source_type` that determines their base confidence before query boosting:

| Source type | Base confidence | Meaning |
|-------------|----------------|---------|
| `changed_file` / `runtime_signal` | 0.95 | Modified in diff or appeared in error stack trace |
| `entrypoint` / `blast_radius` | 0.70–0.90 | Entry function or dependency of a changed file |
| `failing_test` / `contract` | 0.80–0.95 | Test touching changed code; interface/contract file |
| `config` | 0.25 | Config file (yaml/toml/env) |
| `file` | 0.20 | All other symbols — BM25 relevance can raise this up to 0.60+ |
| `call_chain` | 0.45 → 0.315 → 0.22 | Reachable via function call chain from error site (debug mode, depth 1–3) |

**Query scoring (v0.6.0+):** Ranking uses inline Okapi BM25 combined with structural confidence:
`final_conf = min(0.95, 0.6 × structural_conf + 0.4 × bm25_score)`
BM25 scores are normalized across all candidates per query, so the most relevant item always gets the full 0.40 bonus. Items with no query match retain 60% of their structural score.
This replaces the v0.5.x exact-substring additive boost and improves hit rate for queries like "authentication" that didn't match identifiers like `AuthManager` or `verify_token`.

---

## About Review-Mode Hit Rate

Review mode (40% hit rate vs 46.6% random on secret-scan-360) appears to underperform random, which seems counterintuitive. The explanation is a **task suite domain mismatch**, not a ranking bug:

- Review tasks ask about generic web-app concepts: `["api", "endpoint", "router"]`, `["migration", "schema"]`, `["dependency", "requirements", "version"]`
- secret-scan-360 is a **security scanner** — its symbol names are `detect()`, `scan()`, `validate_pattern()` — not API routes or migrations
- Tasks that match the domain (`rev-01`: `["auth", "token", "validate"]`) got **100% hit rate**
- Tasks with no domain overlap (`rev-05`: `["dependency", "requirements", "version"]`) got 0%

Random sampling occasionally hits generic support files (`base.py`, `models.py`) that contain these terms, producing an artificially high random baseline.

**Takeaway:** The 20-task suite is calibrated for general web applications. Run the benchmark against your own codebase (`context-router benchmark run --project-root /path/to/your/repo`) for meaningful, domain-specific quality numbers.

---

## How to Reproduce

```bash
# Initialise and index a project
context-router init --project-root /path/to/repo
context-router index --project-root /path/to/repo

# Run the 20-task benchmark suite
context-router benchmark run --project-root /path/to/repo

# Print the Markdown report
context-router benchmark report --project-root /path/to/repo
```

To adjust the token budget (default 8,000), edit `.context-router/config.yaml`:

```yaml
token_budget: 16000
```

---

## Notes on Methodology

- **Token estimation**: tiktoken `cl100k_base` BPE (accurate Unicode/emoji/code counting).
- **Naive baseline**: sum of all indexed symbol signatures + docstrings with no filtering.
- **Router output**: confidence-ranked symbols within the 8,000-token budget (≥1 item per source type preserved).
- **Latency** includes process startup; warm invocations (benchmark harness) are faster.

_Generated by [context-router](https://github.com/mohankrishnaalavala/context-router) v0.6.0_
