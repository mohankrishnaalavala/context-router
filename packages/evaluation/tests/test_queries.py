from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.queries import Query, QueryFileError, load_queries


def _write(tmp_path: Path, lines: list[dict]) -> Path:
    p = tmp_path / "queries.jsonl"
    with p.open("w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return p


class TestLoadQueries:
    def test_parses_well_formed_lines(self, tmp_path):
        path = _write(tmp_path, [
            {"id": "Q1", "q": "add rate limiting", "gold": ["a.py"], "repos": ["backend"]},
            {"id": "Q2", "q": "show pricing", "gold": ["b.ts"], "repos": ["frontend"]},
        ])
        queries = load_queries(path)
        assert len(queries) == 2
        assert queries[0] == Query(id="Q1", q="add rate limiting", gold=["a.py"], repos=["backend"])

    def test_rejects_missing_id(self, tmp_path):
        path = _write(tmp_path, [{"q": "x", "gold": ["a.py"], "repos": ["r"]}])
        with pytest.raises(QueryFileError, match="missing 'id'"):
            load_queries(path)

    def test_rejects_empty_gold(self, tmp_path):
        path = _write(tmp_path, [{"id": "Q1", "q": "x", "gold": [], "repos": ["r"]}])
        with pytest.raises(QueryFileError, match="empty 'gold'"):
            load_queries(path)

    def test_rejects_duplicate_ids(self, tmp_path):
        path = _write(tmp_path, [
            {"id": "Q1", "q": "x", "gold": ["a.py"], "repos": ["r"]},
            {"id": "Q1", "q": "y", "gold": ["b.py"], "repos": ["r"]},
        ])
        with pytest.raises(QueryFileError, match="duplicate id 'Q1'"):
            load_queries(path)

    def test_skips_blank_lines(self, tmp_path):
        p = tmp_path / "q.jsonl"
        p.write_text('{"id":"Q1","q":"x","gold":["a"],"repos":["r"]}\n\n  \n')
        queries = load_queries(p)
        assert len(queries) == 1
