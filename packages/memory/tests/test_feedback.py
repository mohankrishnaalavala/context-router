"""Tests for FeedbackStore and PackFeedbackRepository."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.models import PackFeedback
from memory.store import FeedbackStore
from storage_sqlite.database import Database

# numpy is optional across this workspace (only sentence-transformers
# pulls it in transitively). The cosine-weighted feedback tests need it
# to synthesise embedding bytes; the production helper itself silent-
# degrades when numpy is missing.
try:
    import numpy as np  # type: ignore[import]
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover - exercised when numpy absent
    _HAS_NUMPY = False


def _emb(values: list[float]) -> bytes:
    """Encode a small float32 vector as bytes for query-embedding tests."""
    return np.asarray(values, dtype=np.float32).tobytes()


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


@pytest.fixture()
def store(db: Database) -> FeedbackStore:
    return FeedbackStore(db)


class TestFeedbackStoreAdd:
    def test_add_returns_id(self, store: FeedbackStore):
        fb = PackFeedback(pack_id="pack-123", useful=True)
        fb_id = store.add(fb)
        assert isinstance(fb_id, str)
        assert len(fb_id) > 0

    def test_add_useful_false(self, store: FeedbackStore):
        fb = PackFeedback(pack_id="pack-123", useful=False, reason="too much noise")
        fb_id = store.add(fb)
        records = store.get_for_pack("pack-123")
        assert len(records) == 1
        assert records[0].useful is False
        assert records[0].reason == "too much noise"

    def test_add_with_missing_and_noisy(self, store: FeedbackStore):
        fb = PackFeedback(
            pack_id="pack-abc",
            missing=["auth.py", "models.py"],
            noisy=["conftest.py"],
        )
        store.add(fb)
        records = store.get_for_pack("pack-abc")
        assert records[0].missing == ["auth.py", "models.py"]
        assert records[0].noisy == ["conftest.py"]

    def test_not_rated_useful_is_none(self, store: FeedbackStore):
        fb = PackFeedback(pack_id="pack-xyz")
        store.add(fb)
        records = store.get_for_pack("pack-xyz")
        assert records[0].useful is None


class TestFeedbackStoreGetAll:
    def test_empty_returns_empty(self, store: FeedbackStore):
        assert store.get_all() == []

    def test_returns_all_records(self, store: FeedbackStore):
        store.add(PackFeedback(pack_id="p1", useful=True))
        store.add(PackFeedback(pack_id="p2", useful=False))
        records = store.get_all()
        assert len(records) == 2

    def test_respects_limit(self, store: FeedbackStore):
        for i in range(5):
            store.add(PackFeedback(pack_id=f"pack-{i}"))
        records = store.get_all(limit=3)
        assert len(records) == 3


class TestAggregateStats:
    def test_empty_stats(self, store: FeedbackStore):
        result = store.aggregate_stats()
        assert result["total"] == 0
        assert result["useful_pct"] == 0.0

    def test_useful_percentage(self, store: FeedbackStore):
        store.add(PackFeedback(pack_id="p1", useful=True))
        store.add(PackFeedback(pack_id="p2", useful=True))
        store.add(PackFeedback(pack_id="p3", useful=False))
        result = store.aggregate_stats()
        assert result["total"] == 3
        assert result["useful_count"] == 2
        assert result["not_useful_count"] == 1
        assert abs(result["useful_pct"] - 66.7) < 0.5

    def test_top_missing_files(self, store: FeedbackStore):
        for _ in range(3):
            store.add(PackFeedback(pack_id="px", missing=["auth.py"]))
        result = store.aggregate_stats()
        assert "auth.py" in result["top_missing"]

    def test_top_noisy_files(self, store: FeedbackStore):
        for _ in range(3):
            store.add(PackFeedback(pack_id="px", noisy=["conftest.py"]))
        result = store.aggregate_stats()
        assert "conftest.py" in result["top_noisy"]


class TestGetFileAdjustments:
    def test_no_adjustments_below_threshold(self, store: FeedbackStore):
        store.add(PackFeedback(pack_id="p1", missing=["auth.py"]))
        store.add(PackFeedback(pack_id="p2", missing=["auth.py"]))
        # Only 2 reports — below min_count=3
        adj = store.get_file_adjustments(min_count=3)
        assert "auth.py" not in adj

    def test_missing_boost_above_threshold(self, store: FeedbackStore):
        for _ in range(3):
            store.add(PackFeedback(pack_id="px", missing=["auth.py"]))
        adj = store.get_file_adjustments(min_count=3)
        assert "auth.py" in adj
        assert adj["auth.py"] == pytest.approx(0.05)

    def test_noisy_penalty_above_threshold(self, store: FeedbackStore):
        for _ in range(3):
            store.add(PackFeedback(pack_id="px", noisy=["conftest.py"]))
        adj = store.get_file_adjustments(min_count=3)
        assert "conftest.py" in adj
        assert adj["conftest.py"] == pytest.approx(-0.10)

    def test_both_missing_and_noisy_combine(self, store: FeedbackStore):
        for _ in range(3):
            store.add(PackFeedback(pack_id="px", missing=["utils.py"], noisy=["utils.py"]))
        adj = store.get_file_adjustments(min_count=3)
        # +0.05 - 0.10 = -0.05
        assert adj["utils.py"] == pytest.approx(-0.05)

    # ------------------------------------------------------------------
    # v4.4 Phase 4: files_read positive signal
    # ------------------------------------------------------------------

    def test_files_read_below_threshold_no_adjustment(self, store: FeedbackStore):
        """Two read reports — below the default min_count=3 threshold."""
        for _ in range(2):
            store.add(PackFeedback(pack_id="p", files_read=["good.py"]))
        adj = store.get_file_adjustments(min_count=3)
        assert "good.py" not in adj

    def test_files_read_positive_boost_above_threshold(self, store: FeedbackStore):
        """Three read reports → +0.03 positive signal (smaller than missing)."""
        for _ in range(3):
            store.add(PackFeedback(pack_id="p", files_read=["good.py"]))
        adj = store.get_file_adjustments(min_count=3)
        assert "good.py" in adj
        assert adj["good.py"] == pytest.approx(0.03)

    def test_files_read_combines_with_noisy(self, store: FeedbackStore):
        """A frequently-read file that is also flagged noisy nets to a small
        negative — explicit noisy outweighs implicit-read."""
        for _ in range(5):
            store.add(PackFeedback(pack_id="p", files_read=["x.py"]))
        for _ in range(3):
            store.add(PackFeedback(pack_id="p", noisy=["x.py"]))
        adj = store.get_file_adjustments(min_count=3)
        # +0.03 (read) - 0.10 (noisy) = -0.07
        assert adj["x.py"] == pytest.approx(-0.07)

    def test_files_read_combines_with_missing(self, store: FeedbackStore):
        """Read + missing both lift the file confidence."""
        for _ in range(3):
            store.add(PackFeedback(pack_id="p", files_read=["y.py"], missing=["y.py"]))
        adj = store.get_file_adjustments(min_count=3)
        # +0.05 (missing) + +0.03 (read) = +0.08
        assert adj["y.py"] == pytest.approx(0.08)


class TestFeedbackStoreScopes:
    def test_add_applies_store_repo_scope(self, db: Database):
        store = FeedbackStore(db, repo_scope="/repo/a")
        store.add(PackFeedback(pack_id="pack-1"))
        row = db.connection.execute(
            "SELECT repo_scope FROM pack_feedback LIMIT 1"
        ).fetchone()
        assert row["repo_scope"] == "/repo/a"

    def test_get_for_pack_filters_to_scope_and_legacy_rows(self, db: Database):
        FeedbackStore(db, repo_scope="/repo/a").add(
            PackFeedback(pack_id="shared-pack", reason="scope-a")
        )
        FeedbackStore(db, repo_scope="/repo/b").add(
            PackFeedback(pack_id="shared-pack", reason="scope-b")
        )
        FeedbackStore(db).add(
            PackFeedback(pack_id="shared-pack", reason="legacy")
        )

        reasons_a = {
            fb.reason for fb in FeedbackStore(db, repo_scope="/repo/a").get_for_pack("shared-pack")
        }
        reasons_b = {
            fb.reason for fb in FeedbackStore(db, repo_scope="/repo/b").get_for_pack("shared-pack")
        }

        assert reasons_a == {"scope-a", "legacy"}
        assert reasons_b == {"scope-b", "legacy"}

    def test_get_all_filters_to_scope_and_legacy_rows(self, db: Database):
        FeedbackStore(db, repo_scope="/repo/a").add(PackFeedback(pack_id="a1", reason="scope-a"))
        FeedbackStore(db, repo_scope="/repo/b").add(PackFeedback(pack_id="b1", reason="scope-b"))
        FeedbackStore(db).add(PackFeedback(pack_id="legacy", reason="legacy"))

        reasons = {
            fb.reason for fb in FeedbackStore(db, repo_scope="/repo/a").get_all(limit=10)
        }
        assert reasons == {"scope-a", "legacy"}

    def test_aggregate_stats_filters_to_scope_and_legacy_rows(self, db: Database):
        scoped = FeedbackStore(db, repo_scope="/repo/a")
        other = FeedbackStore(db, repo_scope="/repo/b")
        legacy = FeedbackStore(db)

        scoped.add(PackFeedback(pack_id="a1", useful=True))
        scoped.add(PackFeedback(pack_id="a2", useful=True))
        other.add(PackFeedback(pack_id="b1", useful=False))
        other.add(PackFeedback(pack_id="b2", useful=False))
        legacy.add(PackFeedback(pack_id="legacy", useful=False))

        result = scoped.aggregate_stats()
        assert result["total"] == 3
        assert result["useful_count"] == 2
        assert result["not_useful_count"] == 1

    def test_file_adjustments_filter_to_scope_and_legacy_rows(self, db: Database):
        scoped = FeedbackStore(db, repo_scope="/repo/a")
        other = FeedbackStore(db, repo_scope="/repo/b")
        legacy = FeedbackStore(db)

        for _ in range(3):
            scoped.add(PackFeedback(pack_id="a", missing=["auth.py"]))
            other.add(PackFeedback(pack_id="b", missing=["billing.py"]))
            legacy.add(PackFeedback(pack_id="legacy", noisy=["legacy.py"]))

        adjustments = scoped.get_file_adjustments(min_count=3)
        assert adjustments["auth.py"] == pytest.approx(0.05)
        assert adjustments["legacy.py"] == pytest.approx(-0.10)
        assert "billing.py" not in adjustments


@pytest.mark.skipif(not _HAS_NUMPY, reason="numpy required for embedding bytes")
class TestQueryConditionalFeedback:
    """v4.4.2 Phase 6: cosine-weighted feedback aggregation."""

    def test_query_embedding_persisted_when_provided(self, store: FeedbackStore):
        """Caller-supplied query_embedding round-trips through the store."""
        emb_bytes = _emb([0.1, 0.2, 0.3, 0.4] * 96)  # 384-dim float32 stub
        fb = PackFeedback(
            pack_id="pack-q1",
            query_text="how does auth work?",
            query_embedding=emb_bytes,
            missing=["auth.py"],
        )
        store.add(fb)
        records = store.get_for_pack("pack-q1")
        assert len(records) == 1
        assert records[0].query_text == "how does auth work?"
        assert records[0].query_embedding == emb_bytes

    def test_legacy_row_with_null_embedding_unweighted(self, store: FeedbackStore):
        """Rows with empty query_embedding contribute their full delta —
        identical to v4.4.1 behaviour, regardless of current_query_embedding."""
        for _ in range(3):
            store.add(PackFeedback(pack_id="px", missing=["auth.py"]))
        # No current embedding → unweighted aggregation, full +0.05.
        adj = store.get_file_adjustments(min_count=3, current_query_embedding=b"")
        assert adj["auth.py"] == pytest.approx(0.05)
        # Non-empty current embedding still yields +0.05 because legacy
        # rows have NULL embeddings → cosine helper returns 1.0 (full delta).
        current = _emb([1.0, 0.0, 0.0, 0.0])
        adj2 = store.get_file_adjustments(min_count=3, current_query_embedding=current)
        assert adj2["auth.py"] == pytest.approx(0.05)

    def test_cosine_weights_full_delta_when_queries_identical(
        self, store: FeedbackStore
    ):
        """Identical query embeddings → cosine = 1.0 → full +0.05 delta."""
        emb = _emb([1.0, 0.0, 0.0, 0.0])
        for _ in range(3):
            store.add(
                PackFeedback(
                    pack_id="px",
                    missing=["auth.py"],
                    query_embedding=emb,
                )
            )
        adj = store.get_file_adjustments(min_count=3, current_query_embedding=emb)
        assert adj["auth.py"] == pytest.approx(0.05)

    def test_cosine_zero_drops_adjustment_to_zero(self, store: FeedbackStore):
        """Orthogonal queries → cosine = 0 → no effective adjustment."""
        row_emb = _emb([1.0, 0.0, 0.0, 0.0])
        for _ in range(3):
            store.add(
                PackFeedback(
                    pack_id="px",
                    missing=["auth.py"],
                    query_embedding=row_emb,
                )
            )
        current = _emb([0.0, 1.0, 0.0, 0.0])
        adj = store.get_file_adjustments(
            min_count=3, current_query_embedding=current
        )
        # Threshold passes (3 raw rows) but weighted multiplier is 0.0.
        assert adj.get("auth.py", 0.0) == pytest.approx(0.0)

    def test_cosine_partial_weight(self, store: FeedbackStore):
        """45-degree query → cosine ≈ 0.7071 → noisy delta ≈ -0.0707."""
        row_emb = _emb([1.0, 0.0])
        for _ in range(3):
            store.add(
                PackFeedback(
                    pack_id="px",
                    noisy=["spam.py"],
                    query_embedding=row_emb,
                )
            )
        current = _emb([0.7071, 0.7071])
        adj = store.get_file_adjustments(
            min_count=3, current_query_embedding=current
        )
        assert adj["spam.py"] == pytest.approx(-0.10 * 0.7071, abs=0.01)

    def test_negative_cosine_clamped_to_zero(self, store: FeedbackStore):
        """Opposing queries (cos = -1) clamp to 0 — no sign-flip allowed."""
        row_emb = _emb([1.0, 0.0])
        for _ in range(3):
            store.add(
                PackFeedback(
                    pack_id="px",
                    missing=["auth.py"],
                    query_embedding=row_emb,
                )
            )
        current = _emb([-1.0, 0.0])
        adj = store.get_file_adjustments(
            min_count=3, current_query_embedding=current
        )
        assert adj.get("auth.py", 0.0) == pytest.approx(0.0)

    def test_min_count_threshold_uses_raw_rows_not_weighted(
        self, store: FeedbackStore
    ):
        """Threshold gates on raw row count; weighting modulates magnitude.

        Two rows fully aligned (cos=1.0) plus one orthogonal (cos=0.0) →
        raw count = 3 (passes threshold), weighted sum / count = 2/3.
        """
        aligned = _emb([1.0, 0.0])
        orthogonal = _emb([0.0, 1.0])
        for _ in range(2):
            store.add(
                PackFeedback(
                    pack_id="px",
                    missing=["auth.py"],
                    query_embedding=aligned,
                )
            )
        store.add(
            PackFeedback(
                pack_id="px",
                missing=["auth.py"],
                query_embedding=orthogonal,
            )
        )
        adj = store.get_file_adjustments(
            min_count=3, current_query_embedding=aligned
        )
        # Threshold gate fires (3 rows); weighted sum = 2.0/3 = 0.667.
        assert adj["auth.py"] == pytest.approx(0.05 * (2 / 3), abs=0.01)
