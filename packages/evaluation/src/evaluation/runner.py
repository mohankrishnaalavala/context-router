"""Runner: loads queries, calls build_pack per query, produces a report."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from evaluation.queries import Query, load_queries
from evaluation.recall import RecallResult, score_recall_at_k
from evaluation.token_efficiency import compute_token_efficiency


@dataclass(frozen=True)
class PackResult:
    files: list[str]
    tokens: int


@dataclass(frozen=True)
class EvalConfig:
    queries_path: Path
    fixture_root: Path
    workspace_roots: list[Path]
    k: int = 20


@dataclass(frozen=True)
class EvalReport:
    recall: RecallResult
    mean_pack_tokens: float
    token_efficiency: float
    n_queries: int
    k: int


BuildPack = Callable[[Query, Path, list[Path]], PackResult]


def run_evaluation(cfg: EvalConfig, build_pack: BuildPack) -> EvalReport:
    queries = load_queries(cfg.queries_path)
    if not queries:
        raise ValueError(f"no queries in {cfg.queries_path}")

    pack_cache: dict[str, PackResult] = {}

    def _fetch(q: Query) -> list[str]:
        result = build_pack(q, cfg.fixture_root, cfg.workspace_roots)
        pack_cache[q.id] = result
        prefix = str(cfg.fixture_root.resolve()).rstrip("/") + "/"
        return [f[len(prefix):] if f.startswith(prefix) else f for f in result.files]

    recall = score_recall_at_k(queries, _fetch, k=cfg.k)
    total_tokens = sum(p.tokens for p in pack_cache.values())
    mean_tokens = total_tokens / len(pack_cache) if pack_cache else 0.0
    return EvalReport(
        recall=recall,
        mean_pack_tokens=mean_tokens,
        token_efficiency=compute_token_efficiency(recall.recall_at_k, mean_tokens),
        n_queries=len(queries),
        k=cfg.k,
    )
