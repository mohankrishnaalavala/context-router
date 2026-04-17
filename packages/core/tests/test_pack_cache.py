"""Tests for P3-1 orchestrator-level TTLCache of ranked ContextPack results."""

from __future__ import annotations

from pathlib import Path

import pytest
from contracts.models import ContextItem, ContextPack


def _make_pack(mode: str = "review", query: str = "test") -> ContextPack:
    return ContextPack(
        mode=mode,
        query=query,
        selected_items=[
            ContextItem(
                source_type="code",
                repo="default",
                path_or_ref="src/a.py",
                title="a",
                reason="r",
                confidence=0.5,
                est_tokens=100,
            )
        ],
        total_est_tokens=100,
        baseline_est_tokens=200,
        reduction_pct=50.0,
    )


class TestPackCache:
    """The TTLCache must avoid re-ranking identical build_pack calls."""

    def test_second_call_is_cache_hit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        # Pre-populate the cache to simulate a prior call without running the
        # whole indexing pipeline (which is the subject of other test modules).
        key = (
            orch._compute_repo_id(),
            "review",
            __import__("hashlib").sha256(b"q").hexdigest(),
            8_000,
            False,
            orch._compute_items_hash(error_file=None, page=0, page_size=0),
        )
        pack = _make_pack()
        orch._pack_cache[key] = pack

        # Spy: if the cache hit path is taken, the inner pipeline is skipped.
        # We assert on identity equality — only a cache hit returns the exact
        # object we stored above.
        call_count = {"n": 0}

        def sentinel(*args, **kwargs):
            call_count["n"] += 1
            raise AssertionError("candidate builder should not run on cache hit")

        monkeypatch.setattr(
            "core.orchestrator._find_project_root",
            lambda *a, **kw: tmp_path,
            raising=False,
        )
        # Fake out the DB existence check and config load so build_pack enters
        # the cache-lookup branch and returns immediately.
        (tmp_path / ".context-router").mkdir(exist_ok=True)
        (tmp_path / ".context-router" / "context-router.db").write_bytes(b"sqlite")

        monkeypatch.setattr(
            "core.orchestrator.load_config",
            lambda *a, **kw: type(
                "Cfg",
                (),
                {
                    "token_budget": 8_000,
                    "modes": {},
                    "confidence_weights": {},
                    "capabilities": type("C", (), {"llm_summarization": False})(),
                    "memory": type("M", (), {"recency_weight": 0.0})(),
                },
            )(),
            raising=False,
        )

        # Recompute the key against the current DB mtime so the pre-populated
        # entry is actually found.
        key = (
            orch._compute_repo_id(),
            "review",
            __import__("hashlib").sha256(b"q").hexdigest(),
            8_000,
            False,
            orch._compute_items_hash(error_file=None, page=0, page_size=0),
        )
        orch._pack_cache[key] = pack

        got = orch.build_pack("review", "q")
        assert got is pack
        assert call_count["n"] == 0

    def test_invalidate_cache_drops_entries(self, tmp_path: Path) -> None:
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        orch._pack_cache[("a",)] = _make_pack()
        orch._pack_cache[("b",)] = _make_pack()
        assert len(orch._pack_cache) == 2

        orch.invalidate_cache()
        assert len(orch._pack_cache) == 0

    def test_repo_id_changes_with_db_mtime(self, tmp_path: Path) -> None:
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        (tmp_path / ".context-router").mkdir()
        db = tmp_path / ".context-router" / "context-router.db"
        db.write_bytes(b"v1")

        id1 = orch._compute_repo_id()

        # Simulate a re-index by changing the DB mtime.
        import os
        import time

        time.sleep(0.01)
        os.utime(db, None)
        id2 = orch._compute_repo_id()

        assert id1 != id2, "repo_id should change when the DB is rewritten"

    def test_items_hash_stable_for_same_inputs(self, tmp_path: Path) -> None:
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        h1 = orch._compute_items_hash(error_file=None, page=0, page_size=0)
        h2 = orch._compute_items_hash(error_file=None, page=0, page_size=0)
        assert h1 == h2

    def test_items_hash_differs_for_different_inputs(self, tmp_path: Path) -> None:
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        h1 = orch._compute_items_hash(error_file=None, page=0, page_size=0)
        h2 = orch._compute_items_hash(error_file=None, page=1, page_size=10)
        assert h1 != h2


class TestUseEmbeddingsPlumbing:
    """Flag propagates CLI → Orchestrator → ContextRanker."""

    def test_ranker_receives_flag(self) -> None:
        from ranking.ranker import ContextRanker

        r_off = ContextRanker(token_budget=1000, use_embeddings=False)
        r_on = ContextRanker(token_budget=1000, use_embeddings=True)
        assert r_off._use_embeddings is False
        assert r_on._use_embeddings is True

    def test_ranker_accepts_progress_cb(self) -> None:
        from ranking.ranker import ContextRanker

        captured: list[str] = []

        def cb(msg: str) -> None:
            captured.append(msg)

        r = ContextRanker(
            token_budget=1000,
            use_embeddings=True,
            progress_cb=cb,
        )
        assert r._progress_cb is cb

    def test_embed_model_cached_check_does_not_raise(self) -> None:
        from ranking.ranker import _embed_model_is_cached

        # Pure existence test — should return a bool either way, never raise.
        result = _embed_model_is_cached()
        assert isinstance(result, bool)
