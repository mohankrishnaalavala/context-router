# context-router v3.0.0 — what changes, in plain English

*For anyone who wants to know what v3 delivers without reading code.*

---

## What context-router does, in one sentence

When an AI coding assistant (Claude, Copilot, Cursor) needs to read your
codebase to answer a question or write code, context-router picks the smallest
useful set of files to show it — so the AI gets the right answer faster,
cheaper, and without flooding its memory with noise.

## Why v3 exists

v2.0 shipped six new features, but our own testing found that:

- The same file would appear in results **three times in a row** (duplicates).
- A flag called `--with-semantic` (for smarter ranking) **did nothing** unless
  used in a specific mode — and never warned the user.
- A speed improvement called "caching" **didn't actually speed anything up**
  when used from the command line.
- Common code patterns (interfaces, test links, inheritance) were **mislabelled
  or missing**, making the results less useful.

v3 fixes all of these, then closes the remaining gaps against the four tools
we compete with (Cursor, Aider, continue.dev, code-review-graph).

---

## What v3 delivers

### Pillar 1 — First impressions that don't embarrass us

| Before v3 | After v3 |
|---|---|
| Running `context-router --version` gives an error. | Running `context-router --version` prints the version number. |
| The same file can appear 3× in results for one query. | Every file appears at most once. |
| Java interfaces and C# records are labelled "class" in the database — making results less accurate for those languages. | Interfaces, records, and enums are labelled correctly. |
| A flag that doesn't apply in your current mode silently does nothing. | If a flag has no effect, you get a warning telling you why. |

### Pillar 2 — Speed that's actually faster

| Before v3 | After v3 |
|---|---|
| Running the same query twice takes the same time both runs. | The second run is at least 2× faster (the cache actually works from the CLI). |
| First use of smarter ranking downloads a 33 MB model with no progress bar, mid-query. | A one-time `embed` step pre-computes this. After that, smarter ranking is as fast as the basic version. |
| Large results come back as one huge JSON blob, slow to display. | Results stream in as they're computed, with progress updates. |

### Pillar 3 — Smarter ranking (catching up to code-review-graph)

| Capability | Before v3 | After v3 |
|---|---|---|
| **Minimal context** — a ≤800-token "just the headline" view for quick triage. | Missing. | New CLI + MCP tool. |
| **Hub / bridge awareness** — files that everyone depends on get a bump. | Missing. | Hub and bridge files rank higher when relevant. |
| **Risk score in review mode** — flags high-churn, high-complexity files. | Missing. | Every item shows low / medium / high risk. |
| **Untested hotspot audit** — lists the most important code with no tests. | Missing. | New `context-router audit --untested-hotspots` command. |

### Pillar 4 — Deeper code understanding

| Capability | Before v3 | After v3 |
|---|---|---|
| `extends` / `implements` relationships between classes. | Not tracked. | Tracked in every language analyzer. |
| "Which tests cover this file?" | Not tracked. | Tracked, and surfaced in review/debug modes. |
| Enums in Java and C#. | Labelled as "class" (wrong). | Labelled as "enum". |
| Function call chains shown as symbols (not just files). | File-level only via CLI/MCP. | Symbol-level exposed everywhere. |
| Cross-service contracts (OpenAPI / gRPC / GraphQL). | Detected but not used in single-repo results. | Boost applied — if your code calls an API endpoint defined in an OpenAPI spec, the implementing file ranks higher. |

### Pillar 5 — Handover & flow-level reasoning

| Capability | Before v3 | After v3 |
|---|---|---|
| Handover mode gives a file list. | New `--wiki` flag generates a multi-section Markdown summary of the top subsystems — one doc an incoming engineer can read to ramp up. |
| Debug mode walks 3 hops of call-chain edges. | Debug mode groups results by **execution flow** (entry point → failure point), which is what engineers actually trace. |

### Pillar 6 — MCP compliance polish

MCP is the standard that lets Claude, Copilot, and other AI tools talk to
context-router. Small gaps here make integration awkward.

| Before v3 | After v3 |
|---|---|
| MCP responses omit the `mimeType` field. | Every response has the right content type. |
| MCP `serverInfo` reports the wrong version. | Reports the actual installed version. |
| Large packs block the connection until the whole payload is ready. | Progress notifications stream during long builds. |

### Pillar 7 — Benchmarks the community can trust

| Before v3 | After v3 |
|---|---|
| README shows benchmark numbers with no confidence interval. | Every number has a 95% confidence interval (so you know if it's a real improvement or noise). |
| Benchmarks only run on the `main` branch — regressions found late. | Benchmarks run on every push to `develop` — regressions caught before merge. |
| Only one baseline ("naive keyword search"). | Two baselines (keyword + code-review-graph) so users can see how we compare. |

---

## Competitive scorecard — where v3 takes us

Green = feature works. Yellow = partial. Red = missing.

| Capability | context-router v2 today | context-router v3 target | Cursor | Aider | continue.dev | code-review-graph |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| Multi-language monorepo support | 🟢 | 🟢 | 🟡 | 🟡 | 🟡 | 🟢 |
| Persistent feedback loop | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| BM25 + semantic hybrid ranking | 🟢 | 🟢 | 🟡 | 🟡 | 🟡 | 🟡 |
| MCP spec compliance | 🟡 | 🟢 | 🔴 | 🔴 | 🟡 | 🟢 |
| Cross-language contracts | 🟡 | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| Semantic mode discoverability | 🔴 | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| Dedup in output | 🔴 | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| Streaming large packs | 🔴 | 🟢 | 🟢 | 🟢 | 🟡 | 🟡 |
| Function-level call graph (surfaced) | 🔴 | 🟢 | 🟢 | 🟢 | 🟢 | 🟢 |
| TESTED_BY edges | 🔴 | 🟢 | 🟡 | 🔴 | 🔴 | 🟢 |
| Inherits / extends / implements edges | 🔴 | 🟢 | 🔴 | 🔴 | 🔴 | 🟢 |
| Hub / bridge node metrics | 🔴 | 🟢 | 🔴 | 🔴 | 🔴 | 🟢 |
| Token-minimal context tool | 🔴 | 🟢 | 🔴 | 🔴 | 🔴 | 🟢 |
| Flow-level reasoning | 🔴 | 🟢 | 🔴 | 🔴 | 🔴 | 🟢 |
| Wiki / knowledge-gap surfaces | 🔴 | 🟢 | 🔴 | 🔴 | 🔴 | 🟢 |
| Task routing by mode (implement/review/debug/handover) | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| Token budget (knapsack) | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |
| Project memory (observations / decisions) | 🟢 | 🟢 | 🔴 | 🔴 | 🔴 | 🔴 |

**After v3, no competitor has a green where we have a red.** We also keep five
green rows where no one else has a green — those are our moat.

---

## How we'll know v3 is actually good

Every item above has a matching entry in
[`docs/release/v3-outcomes.yaml`](./v3-outcomes.yaml) with a specific command
anyone can run to prove it works. A script called `scripts/smoke-v3.sh` runs
all of them and only prints "PASS" when the user-visible behavior matches.
No feature is "done" until that script says PASS for it.

Starting baseline (2026-04-17, before any v3 work): 1 PASS / 22 FAIL.
Release baseline (2026-04-18, `v3.0.0` tag): 20 PASS / 4 FAIL, where all
four remaining FAILs are known documented items (two need
`sentence-transformers` installed in the runner, one is a smoke-query
tuning item, one is a fixture-with-no-diff issue). The release is live on
`main` and tagged.

---

## What actually happened: real-repo measurements

*Numbers below are measured against three real OSS repos after v3.0.0 shipped. Details in [`internal_docs/production-readiness-review-v3.md`](../../internal_docs/production-readiness-review-v3.md).*

### Three OSS repos tested

| Repo | Language | Files | Symbols | Edges indexed |
|---|---|---|---|---|
| bulletproof-react | TypeScript / React | 426 | 769 | 463 |
| eShopOnWeb | C# / .NET | 352 | 1,386 | 716 |
| spring-petclinic | Java / Spring | 48 | 217 | 347 |

### Speed — how much faster v3 got

End-to-end wall time for `context-router pack --mode implement` (CLI startup + pipeline):

| Repo | v3 cold | v3 warm (cache hit) | Warm/cold (inner pipeline) |
|---|---|---|---|
| bulletproof-react | 0.79 s | 0.71 s | **8.5× faster** |
| eShopOnWeb | 0.89 s | 0.68 s | **12× faster** |
| spring-petclinic | 0.71 s | 0.64 s | **3.7× faster** |

Across all three repos, v3 is **35–49 % faster than v2** end-to-end. The
pipeline-internal speedup from the new SQLite cache is much larger (up to
12×), but roughly half a second of every CLI run is always spent on
interpreter / rich startup, which dampens the visible improvement. This
is the honest number — we did not hide startup cost behind a flag.

### Token reduction — how much less text the AI has to read

Measured against a naive "all files in the repo" baseline:

| Repo | v3 reduction |
|---|---|
| context-router (this repo, self-benchmark) | **94.8 %** |
| bulletproof-react | **78.7 %** |
| eShopOnWeb | **90.4 %** |
| spring-petclinic | **52.6 %** |

Meaning: on eShopOnWeb, v3 selects a context pack roughly one tenth the
size of the naive baseline, while keeping the relevant files at the top
of the list.

### Graph quality — do the new edges actually point at the right things?

After v3's edge-extraction fixes (#48 + #60):

| Repo | `extends` | `implements` | `tested_by` | Constructor-anchored edges (should be 0) | `Task`-targeted `tested_by` (should be 0) |
|---|---|---|---|---|---|
| eShopOnWeb | 126 | 44 | 41 | **0** ✅ | **0** ✅ |
| spring-petclinic | 11 | 6 | 38 | **0** ✅ | **0** ✅ |
| bulletproof-react | 0 | 0 | 0 | n/a | n/a |

bulletproof-react's zero count is an honest finding: the TypeScript analyzer
emits these edges only on class-based code, and bulletproof-react is
function-components + JSX. This is tracked as a v3.1 follow-up.

### Competitive scorecard — actual status after v3 tag

Compared with code-review-graph (CRG), we closed 6 of 6 rows where CRG
previously led. All of our v2 moats (task routing, memory, token budget,
BM25, pack cache) are retained. One CRG parity row stays **yellow** —
flow-level reasoning — because we annotate debug items with flow labels
but don't ship a standalone `list_flows` tool yet.

### MCP spec compliance

**8 of 8** items pass the MCP 2024-11-05 compliance audit. Notable:
- Every `tools/call` response content block has a `mimeType`.
- `initialize.serverInfo.version` correctly returns `3.0.0`.
- Large MCP packs emit **11 progress notifications** before the final
  response; small packs emit **0** (no spurious noise on tiny queries).
- The new `get_minimal_context` tool rejects empty task strings cleanly
  instead of returning a garbage response.

### What's queued for v3.1

The 7-prompt post-release audit surfaced a small punch list (full
details in the production readiness review). Highlights:

1. **Homebrew formula version** — still at `0.3.0`; tap-repo update
   pending (P0 for `brew install` users).
2. **TypeScript edge coverage** — extend to function-only React +
   JSX-rendered test patterns (P1).
3. **Benchmark keyword-baseline reporting** — currently clamps a
   legitimate -47 % to "-0 %", which is misleading (P0 honesty bug).
4. **Minimal-mode ranker tuning** — for task-verb queries like
   "add visit" on Spring (P1).
5. **Docs sync** — README lists 16 MCP tools; actual count is 17 (P1,
   cheap).
6. **Hub/bridge boost smoke query** — unit tests pass; end-to-end query
   currently uses a BM25-dominated top-5 that can't flip under the
   +0.10 cap (P3 smoke tuning).

None of the above blocks v3.0.0 adoption. They ship in v3.1.
