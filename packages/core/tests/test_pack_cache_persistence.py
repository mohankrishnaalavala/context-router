"""Tests for the persistent L2 pack cache (SQLite-backed, migration 0012).

v2.0.0 shipped `cachetools.TTLCache` on the Orchestrator instance — the cache
died with the CLI process so two identical `context-router pack` runs both
ran the full pipeline. The L2 cache in this module persists packs to SQLite
so a fresh Orchestrator instance (new CLI process) can hit the cache and
skip candidate building + ranking entirely.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from contracts.models import ContextItem, ContextPack
from storage_sqlite.database import Database
from storage_sqlite.repositories import PackCacheRepository


def _make_pack(query: str = "persist me", mode: str = "implement") -> ContextPack:
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


def _init_db(tmp_path: Path) -> Path:
    """Create a .context-router/ dir with an initialized DB. Returns db path."""
    (tmp_path / ".context-router").mkdir(exist_ok=True)
    db_path = tmp_path / ".context-router" / "context-router.db"
    with Database(db_path) as db:
        # triggers migrations — creates pack_cache table among others
        _ = db.connection
    return db_path


def _stub_config(monkeypatch: pytest.MonkeyPatch, token_budget: int = 8_000) -> None:
    """Replace load_config with a minimal stub so build_pack short-circuits
    into the cache lookup branch without parsing a real project."""
    monkeypatch.setattr(
        "core.orchestrator.load_config",
        lambda *a, **kw: type(
            "Cfg",
            (),
            {
                "token_budget": token_budget,
                "modes": {},
                "confidence_weights": {},
                "capabilities": type("C", (), {"llm_summarization": False})(),
                "memory": type("M", (), {"recency_weight": 0.0})(),
            },
        )(),
        raising=False,
    )


class TestPackCachePersistence:
    """Scenarios that v2.0.0's in-process-only cache failed to handle."""

    def test_second_orchestrator_instance_hits_l2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two sequential build_pack calls with different Orchestrator
        instances (new process simulated) → second call returns a cached
        pack without re-ranking."""
        from core.orchestrator import Orchestrator

        _init_db(tmp_path)
        _stub_config(monkeypatch)

        # Orchestrator A: warm the L2 cache directly. We bypass the full
        # pipeline by writing via the repository — equivalent to a successful
        # prior build_pack that populated both L1 and L2.
        orch_a = Orchestrator(project_root=tmp_path)
        pack = _make_pack(query="q")
        query_hash = hashlib.sha256(b"q").hexdigest()
        items_hash = orch_a._compute_items_hash(error_file=None, page=0, page_size=0)
        repo_id = orch_a._compute_repo_id()
        cache_key_str = orch_a._cache_key_string("implement", query_hash, 8_000, False, items_hash)
        db_path = tmp_path / ".context-router" / "context-router.db"
        with Database(db_path) as db:
            PackCacheRepository(db.connection).put(cache_key_str, repo_id, pack.model_dump_json())

        # Orchestrator B: fresh instance (empty L1). Must still hit L2.
        orch_b = Orchestrator(project_root=tmp_path)
        assert len(orch_b._pack_cache) == 0  # L1 is cold

        # Spy on the candidate builder: it must NOT run on an L2 hit.
        calls: list[str] = []

        def _no_candidates(*_args: Any, **_kwargs: Any) -> None:
            calls.append("ran")
            raise AssertionError("candidate pipeline should not run on L2 hit")

        monkeypatch.setattr(orch_b, "_build_candidates", _no_candidates)

        got = orch_b.build_pack("implement", "q")
        assert calls == []
        # Equivalence by identity isn't guaranteed across processes, so assert
        # by content — the pack was round-tripped through JSON and rebuilt.
        assert got.query == "q"
        assert got.mode == "implement"
        assert got.total_est_tokens == pack.total_est_tokens
        # L1 was re-hydrated from L2 so a third same-process call is a
        # pure L1 hit.
        assert len(orch_b._pack_cache) == 1

    def test_update_index_invalidates_l2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After `update_index` bumps the DB mtime, repo_id changes, so the
        next build_pack with the same query is a miss."""
        from core.orchestrator import Orchestrator

        db_path = _init_db(tmp_path)
        _stub_config(monkeypatch)

        orch = Orchestrator(project_root=tmp_path)
        repo_id_before = orch._compute_repo_id()
        query_hash = hashlib.sha256(b"q").hexdigest()
        items_hash = orch._compute_items_hash(error_file=None, page=0, page_size=0)
        cache_key_str = orch._cache_key_string("implement", query_hash, 8_000, False, items_hash)
        pack = _make_pack("q")

        with Database(db_path) as db:
            PackCacheRepository(db.connection).put(
                cache_key_str, repo_id_before, pack.model_dump_json()
            )

        # Simulate an `update_index` run: a new symbol row appears, which
        # bumps COUNT/MAX(id) and therefore repo_id. invalidate_cache is
        # the belt-and-suspenders call the index tools make.
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO symbols(repo, file_path, name, kind) VALUES(?, ?, ?, ?)",
                ("default", "src/new.py", "new", "function"),
            )
            conn.commit()
        orch.invalidate_cache()

        # Now the repo_id has rotated AND the row has been deleted — a
        # build_pack call must re-run the pipeline.
        repo_id_after = orch._compute_repo_id()
        assert repo_id_after != repo_id_before

        called: list[str] = []

        def _record(*_a: Any, **_k: Any) -> None:
            called.append("ran")
            raise RuntimeError("stop here — we only care that the candidate pipeline was entered")

        monkeypatch.setattr(orch, "_build_candidates", _record)
        with pytest.raises(RuntimeError):
            orch.build_pack("implement", "q")
        assert called == ["ran"], "cache must miss after re-index"

    def test_ttl_expiration_forces_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Advance time.time past 300s → the L2 entry is treated as a miss."""
        from core.orchestrator import Orchestrator

        db_path = _init_db(tmp_path)
        _stub_config(monkeypatch)

        orch = Orchestrator(project_root=tmp_path)
        query_hash = hashlib.sha256(b"q").hexdigest()
        items_hash = orch._compute_items_hash(error_file=None, page=0, page_size=0)
        repo_id = orch._compute_repo_id()
        cache_key_str = orch._cache_key_string("implement", query_hash, 8_000, False, items_hash)
        pack = _make_pack("q")

        t0 = 1_000_000.0
        with Database(db_path) as db:
            PackCacheRepository(db.connection).put(
                cache_key_str, repo_id, pack.model_dump_json(), now=t0
            )

        # A read within TTL succeeds.
        with Database(db_path) as db:
            got = PackCacheRepository(db.connection).get(
                cache_key_str,
                repo_id,
                float(orch._PACK_CACHE_TTL_SECONDS),
                now=t0 + 100,
            )
        assert got is not None, "within-TTL read should hit"

        # A read past TTL is a miss.
        with Database(db_path) as db:
            got = PackCacheRepository(db.connection).get(
                cache_key_str,
                repo_id,
                float(orch._PACK_CACHE_TTL_SECONDS),
                now=t0 + orch._PACK_CACHE_TTL_SECONDS + 1,
            )
        assert got is None, "post-TTL read must miss"

    def test_use_embeddings_key_isolation(self, tmp_path: Path) -> None:
        """Semantic and lexical runs must not collide in the L2 cache."""
        from core.orchestrator import Orchestrator

        orch = Orchestrator(project_root=tmp_path)
        query_hash = hashlib.sha256(b"q").hexdigest()
        items_hash = orch._compute_items_hash(error_file=None, page=0, page_size=0)
        lexical = orch._cache_key_string("implement", query_hash, 8_000, False, items_hash)
        semantic = orch._cache_key_string("implement", query_hash, 8_000, True, items_hash)
        assert lexical != semantic, "use_embeddings must be part of the L2 cache key"

    def test_l1_regression_same_process_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pre-existing L1 (TTLCache) behavior still works — same-process
        callers still get the fastest path."""
        from core.orchestrator import Orchestrator

        _init_db(tmp_path)
        _stub_config(monkeypatch)

        orch = Orchestrator(project_root=tmp_path)
        pack = _make_pack("q")
        query_hash = hashlib.sha256(b"q").hexdigest()
        items_hash = orch._compute_items_hash(error_file=None, page=0, page_size=0)
        cache_key = (
            orch._compute_repo_id(),
            "implement",
            query_hash,
            8_000,
            False,
            items_hash,
        )
        orch._pack_cache[cache_key] = pack

        # L1 hit must return the exact object (identity equality) without
        # any L2 read.
        def _no_l2(*_a: Any, **_k: Any) -> None:
            raise AssertionError("L2 should not be consulted on an L1 hit")

        monkeypatch.setattr(orch, "_l2_get", _no_l2)
        got = orch.build_pack("implement", "q")
        assert got is pack


class TestPackCacheRepositoryDirect:
    """Unit tests for the repository contract itself — exercised by the
    L2 helpers above but worth pinning independently."""

    def test_insert_replace_is_idempotent(self, tmp_path: Path) -> None:
        with Database(tmp_path / "c.db") as db:
            repo = PackCacheRepository(db.connection)
            repo.put("k", "r", '{"v":1}', now=100.0)
            repo.put("k", "r", '{"v":2}', now=101.0)
            got = repo.get("k", "r", 3600.0, now=102.0)
        assert got == '{"v":2}'

    def test_invalidate_repo_scoped(self, tmp_path: Path) -> None:
        with Database(tmp_path / "c.db") as db:
            repo = PackCacheRepository(db.connection)
            repo.put("k", "r1", "a", now=100.0)
            repo.put("k", "r2", "b", now=100.0)
            repo.invalidate_repo("r1")
            assert repo.get("k", "r1", 3600.0, now=101.0) is None
            assert repo.get("k", "r2", 3600.0, now=101.0) == "b"
