"""Recall@K scorer for context-router packs."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from evaluation.queries import Query


@dataclass(frozen=True)
class QueryResult:
    id: str
    hit: bool
    missing: list[str]
    returned: list[str]


@dataclass(frozen=True)
class RecallResult:
    recall_at_k: float
    k: int
    per_query: list[QueryResult]
    total: int = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "total", len(self.per_query))


def _normalise(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def score_recall_at_k(
    queries: list[Query],
    fetch: Callable[[Query], list[str]],
    k: int,
) -> RecallResult:
    if not queries:
        raise ValueError("no queries to score")
    per_query: list[QueryResult] = []
    hits = 0
    for q in queries:
        returned = [_normalise(p) for p in fetch(q)][:k]
        returned_set = set(returned)
        gold = {_normalise(g) for g in q.gold}
        missing = sorted(gold - returned_set)
        hit = not missing
        if hit:
            hits += 1
        per_query.append(QueryResult(id=q.id, hit=hit, missing=missing, returned=returned))
    return RecallResult(recall_at_k=hits / len(queries), k=k, per_query=per_query)
