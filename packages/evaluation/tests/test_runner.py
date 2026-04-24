from __future__ import annotations

import json
from pathlib import Path

from evaluation.queries import Query
from evaluation.runner import EvalConfig, PackResult, run_evaluation


def _write_queries(tmp_path: Path) -> Path:
    p = tmp_path / "q.jsonl"
    p.write_text(
        json.dumps({"id": "Q1", "q": "x", "gold": ["a.py"], "repos": ["r1"]}) + "\n"
        + json.dumps({"id": "Q2", "q": "y", "gold": ["b.py"], "repos": ["r2"]}) + "\n"
    )
    return p


class TestRunEvaluation:
    def test_happy_path_builds_report(self, tmp_path):
        qpath = _write_queries(tmp_path)

        def fake_build_pack(
            q: Query, project_root: Path, workspace_roots: list[Path]
        ) -> PackResult:
            return PackResult(files=["a.py"] if q.id == "Q1" else ["x.py"], tokens=500)

        cfg = EvalConfig(
            queries_path=qpath, fixture_root=tmp_path, workspace_roots=[tmp_path], k=20
        )
        out = run_evaluation(cfg, build_pack=fake_build_pack)
        assert out.recall.recall_at_k == 0.5
        assert out.mean_pack_tokens == 500.0
        assert out.token_efficiency == 0.5 / 500 * 1000
        assert out.n_queries == 2

    def test_records_per_query_miss_list(self, tmp_path):
        qpath = _write_queries(tmp_path)
        cfg = EvalConfig(
            queries_path=qpath, fixture_root=tmp_path, workspace_roots=[tmp_path], k=20
        )
        out = run_evaluation(cfg, build_pack=lambda *_: PackResult(files=[], tokens=100))
        assert {r.id for r in out.recall.per_query if not r.hit} == {"Q1", "Q2"}
