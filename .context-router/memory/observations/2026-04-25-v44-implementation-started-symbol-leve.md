---
id: 2026-04-25-v44-implementation-started-symbol-leve
type: observation
task: implement
files_touched:
  - docs/superpowers/plans/2026-04-25-v4.4-roadmap.md
  - docs/release/v4-outcomes.yaml
created_at: 2026-04-25T23:34:45.249830+00:00
author: context-router
---

v4.4 implementation started: symbol-level packs, holdout benchmark, 10-language support, retrieval quality fixes

v4.4 plan finalised: Phase A adds holdout benchmark (gin/rails/actix/django) + downstream token measurement. Phase B adds symbol_body to ContextItem so agents receive actual code bodies not file pointers (target: downstream read <=500 tokens). Phase C adds source-file boost (oauth2-query->oauth2.py fix generalised) and enables semantic re-rank by default + lowers ABS_FLOOR 0.45->0.40 (target: tuning F1 >=0.50). Phase D adds Go(go), Rust(rs), Ruby(rb), PHP(php), SQL(sql), JavaScript(js) language analyzers reaching 10 supported languages. Judge benchmark showed v4.3 F1=0.394 vs v3.3.0 F1=0.577 — structural fixes needed not constant tuning.
