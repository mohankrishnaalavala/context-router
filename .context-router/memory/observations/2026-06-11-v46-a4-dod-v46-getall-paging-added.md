---
id: 2026-06-11-v46-a4-dod-v46-getall-paging-added
type: observation
task: implement
files_touched:
  - packages/storage-sqlite/src/storage_sqlite/repositories.py
  - packages/storage-sqlite/tests/test_iter_all_paging.py
  - packages/core/src/core/orchestrator.py
  - packages/core/tests/test_getall_paging.py
  - packages/core/tests/test_implement_fts_anchor.py
  - packages/graph-index/src/graph_index/flows.py
created_at: 2026-06-11T02:53:05.893446+00:00
author: context-router
---

v4.6 A4 (DoD v4.6-getall-paging): added SymbolRepository.iter_all keyset paging (no cap, batch_size=5000); converted pack-time get_all consumers — 4 orchestrator sites plus graph_index.flows.list_flows (2 calls, caught by debug-mode test) — so ranking covers the full symbol set with no cap WARN. get_all keeps 10k cap; WARN now suggests iter_all. FTS-zero-hits warning reworded (no longer claims 10K slice), tests pin iter_all instead of get_all. Note: venv shadowing — must run `uv sync --all-packages --extra dev --reinstall-package context-router-cli` after source edits (cli wheel vendors all packages concretely, shadowing editable .pth installs). Commits c004a15 (storage) + 9fc8f2a (core/graph-index) on develop, not pushed.
