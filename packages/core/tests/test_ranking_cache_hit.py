"""v3.3.0 β5 — integration test: second build_pack call is a cache hit.

Builds a real pack end-to-end, then builds it again with identical
arguments. The second call must come from the TTLCache — we prove it by
spying on the BM25 corpus constructor (``rank_bm25.BM25Okapi``) and
asserting it's called exactly once across the two build_pack calls.

A cache miss would re-run the ranker and increment the call count on
the second run; a cache hit returns the stored pack immediately.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_fixture_tree(tmp_path: Path, n_files: int = 60) -> None:
    """Seed the tmp_path with a context-router project + symbols.

    Fewer than ``n_files`` symbols and the cache key's ``items_hash``
    still differs on TTL boundaries. We stay well above 50 so the
    v3-outcomes threshold (pack-cache-persists-cli) is also respected
    if this fixture is reused elsewhere.
    """
    (tmp_path / ".context-router").mkdir(parents=True, exist_ok=True)
    from contracts.interfaces import Symbol
    from storage_sqlite.database import Database
    from storage_sqlite.repositories import SymbolRepository

    db_path = tmp_path / ".context-router" / "context-router.db"
    with Database(db_path) as db:
        symbols = [
            Symbol(
                name=f"fn_{i}",
                kind="function",
                file=tmp_path / "src" / f"mod_{i}.py",
                line_start=1,
                line_end=3,
                language="python",
                signature=f"def fn_{i}():",
                docstring="",
            )
            for i in range(n_files)
        ]
        SymbolRepository(db.connection).add_bulk(symbols, "default")


class TestRankingCacheHit:
    def test_second_build_pack_is_cache_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.orchestrator import Orchestrator

        _write_fixture_tree(tmp_path)

        # Spy on the ranker's BM25 corpus constructor. The ranker
        # instantiates a ``_BM25Scorer`` every time it scores candidates
        # against a query — a cache hit bypasses that constructor
        # entirely on the second call, so the counter stays frozen.
        construct_count = {"n": 0}
        import ranking.ranker as _ranker

        real_init = _ranker._BM25Scorer.__init__

        def _counting_init(self, docs, *args, **kwargs):  # type: ignore[no-untyped-def]
            construct_count["n"] += 1
            real_init(self, docs, *args, **kwargs)

        monkeypatch.setattr(
            _ranker._BM25Scorer, "__init__", _counting_init, raising=True
        )

        orch = Orchestrator(project_root=tmp_path)
        first = orch.build_pack("implement", "find fn_1")
        miss_count = construct_count["n"]
        assert miss_count >= 1, (
            "first call should construct BM25 at least once (cache miss)"
        )

        # Second identical call — must be a cache hit.
        second = orch.build_pack("implement", "find fn_1")
        assert construct_count["n"] == miss_count, (
            "second call hit _BM25Scorer.__init__ again — cache miss!"
        )
        # And we return the same pack object from the in-memory cache.
        assert first.id == second.id

    def test_different_query_is_cache_miss(
        self, tmp_path: Path
    ) -> None:
        from core.orchestrator import Orchestrator

        _write_fixture_tree(tmp_path)
        orch = Orchestrator(project_root=tmp_path)

        first = orch.build_pack("implement", "find fn_1")
        second = orch.build_pack("implement", "find fn_99")

        # Different queries must produce distinct packs — we don't want
        # the cache to collide across keys.
        assert first.query != second.query
