"""Load queries.jsonl files for Recall@K evaluation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class QueryFileError(ValueError):
    """Raised when queries.jsonl is malformed."""


@dataclass(frozen=True)
class Query:
    id: str
    q: str
    gold: frozenset[str]
    repos: frozenset[str]

    def __init__(self, id: str, q: str, gold, repos):
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "q", q)
        object.__setattr__(self, "gold", frozenset(gold))
        object.__setattr__(self, "repos", frozenset(repos))

    def __eq__(self, other):
        if not isinstance(other, Query):
            return NotImplemented
        return (
            self.id == other.id
            and self.q == other.q
            and self.gold == other.gold
            and self.repos == other.repos
        )

    def __hash__(self):
        return hash((self.id, self.q, self.gold, self.repos))


def load_queries(path: Path) -> list[Query]:
    queries: list[Query] = []
    seen: set[str] = set()
    with Path(path).open() as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise QueryFileError(f"line {lineno}: invalid JSON — {exc}") from exc
            if "id" not in obj:
                raise QueryFileError(f"line {lineno}: missing 'id' field")
            if "q" not in obj:
                raise QueryFileError(f"line {lineno}: missing 'q' field")
            if not obj.get("gold"):
                raise QueryFileError(f"line {lineno}: empty 'gold' list")
            if obj["id"] in seen:
                raise QueryFileError(f"line {lineno}: duplicate id {obj['id']!r}")
            seen.add(obj["id"])
            queries.append(Query(
                id=obj["id"],
                q=obj["q"],
                gold=obj["gold"],
                repos=obj.get("repos", []),
            ))
    return queries
