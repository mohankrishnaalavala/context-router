from __future__ import annotations

import pytest
from evaluation.queries import Query
from evaluation.recall import score_recall_at_k


def _mk(id_: str, gold: list[str]) -> Query:
    return Query(id=id_, q=f"query {id_}", gold=gold, repos=[])


class TestRecallAtK:
    def test_all_hits(self):
        queries = [_mk("Q1", ["a.py", "b.py"])]
        out = score_recall_at_k(queries, lambda q: ["a.py", "b.py", "c.py"], k=20)
        assert out.recall_at_k == 1.0
        assert out.per_query[0].hit is True
        assert out.per_query[0].missing == []

    def test_partial_hit_counts_as_miss(self):
        queries = [_mk("Q1", ["a.py", "b.py"])]
        out = score_recall_at_k(queries, lambda q: ["a.py", "x.py"], k=20)
        assert out.recall_at_k == 0.0
        assert out.per_query[0].hit is False
        assert out.per_query[0].missing == ["b.py"]

    def test_k_truncates_candidate_list(self):
        queries = [_mk("Q1", ["b.py"])]
        fetch = lambda q: ["a.py", "x.py", "y.py", "b.py"]  # noqa: E731
        assert score_recall_at_k(queries, fetch, k=3).recall_at_k == 0.0
        assert score_recall_at_k(queries, fetch, k=4).recall_at_k == 1.0

    def test_mean_over_multiple_queries(self):
        queries = [_mk("Q1", ["a.py"]), _mk("Q2", ["b.py"])]
        out = score_recall_at_k(queries, lambda q: ["a.py"] if q.id == "Q1" else [], k=20)
        assert out.recall_at_k == 0.5

    def test_empty_queries_raises(self):
        with pytest.raises(ValueError, match="no queries"):
            score_recall_at_k([], lambda q: [], k=20)

    def test_path_normalisation_forward_slashes(self):
        queries = [_mk("Q1", ["backend/src/a.py"])]
        out = score_recall_at_k(queries, lambda q: ["backend\\src\\a.py"], k=20)
        assert out.recall_at_k == 1.0
