---
id: 2026-06-10-token-efficiency-diagnosis-3-root-cause
type: observation
task: debug
files_touched:
  - packages/contracts/src/contracts/config.py
  - benchmarks/results/2026-04-29-k8s-comparison/summary.json
  - docs/superpowers/plans/2026-04-25-v4.4-roadmap.md
created_at: 2026-06-10T01:25:07.823628+00:00
author: context-router
---

Token-efficiency diagnosis: 3 root causes found. (1) Index pollution — 44,661 of 48,970 symbols (91%) are from .venv-crg/ site-packages because ignore_patterns in packages/contracts/src/contracts/config.py:78 only matches literal '.venv' (no .venv-*, no node_modules, no gitignore-awareness); handover pack on own repo returned 89/91 items from fastmcp/jwt/docutils noise at 7,889 tokens. (2) Benchmark measures pack-pointer tokens (est_tokens 169 vs CRG 1101 on k8s, n=3) not end-to-end agent tokens — packs return file POINTERS, downstream agent still reads full files, so real-world saving is unproven. (3) Retrieval quality regression: judge F1 0.394 (v4.3) vs 0.577 (v3.3.0), v4.4 roadmap phases B/C written to fix it but unshipped. Competitor contrast: claude-mem saves tokens passively via Read-hooks + injected timeline, no voluntary tool calls needed; context-router requires agent cooperation and returns pointers not content.

No fix applied yet — assessment delivered to user. Recommended order: P0 gitignore-aware indexing + reindex, P1 end-to-end downstream-token benchmark with model judge, P2 ship symbol bodies in packs (v4.4 Phase B) so agents stop re-reading files.
