# tests/fixtures/workspaces/real/

Populated by `scripts/fetch-benchmark-repos.sh`. Repos are cloned at pinned
SHAs so evaluation runs are reproducible. The cloned source is NOT
committed; only each repo's `queries.jsonl` lives in-tree.

To populate:

```
./scripts/fetch-benchmark-repos.sh
```

To add a fixture: pin it in the script and add a `queries.jsonl` beside
this README.
