"""Tests for FeedbackStore and PackFeedbackRepository."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.models import PackFeedback
from memory.store import FeedbackStore
from storage_sqlite.database import Database


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
