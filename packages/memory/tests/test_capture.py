"""Tests for the memory.capture guardrail module."""

from __future__ import annotations

import pytest

from contracts.models import Observation
from memory.capture import (
    capture_observation,
    make_task_hash,
    redact_secrets,
    should_capture,
)


class TestMakeTaskHash:
    def test_returns_16_char_hex(self):
        h = make_task_hash("debug", "fixed auth bug")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_inputs_same_hash(self):
        h1 = make_task_hash("debug", "fixed auth bug")
        h2 = make_task_hash("debug", "fixed auth bug")
        assert h1 == h2

    def test_different_task_type_different_hash(self):
        h1 = make_task_hash("debug", "fixed auth bug")
        h2 = make_task_hash("implement", "fixed auth bug")
        assert h1 != h2

    def test_different_summary_different_hash(self):
        h1 = make_task_hash("debug", "fixed auth bug")
        h2 = make_task_hash("debug", "fixed session bug")
        assert h1 != h2

    def test_truncates_summary_at_80_chars(self):
        long_summary = "x" * 200
        short_summary = "x" * 80
        h1 = make_task_hash("general", long_summary)
        h2 = make_task_hash("general", short_summary)
        assert h1 == h2

    def test_empty_inputs_do_not_raise(self):
        h = make_task_hash("", "")
        assert len(h) == 16


class TestRedactSecrets:
    def test_redacts_password_equals(self):
        result = redact_secrets("export PASSWORD=supersecret")
        assert "supersecret" not in result
        assert "REDACTED" in result

    def test_redacts_token_colon(self):
        result = redact_secrets("token: abc123xyz")
        assert "abc123xyz" not in result
        assert "REDACTED" in result

    def test_redacts_bearer_token(self):
        result = redact_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig")
        assert "eyJhbGciOiJIUzI1NiJ9" not in result
        assert "REDACTED" in result

    def test_safe_text_unchanged(self):
        text = "uv run pytest --tb=short"
        assert redact_secrets(text) == text

    def test_api_key_redacted(self):
        result = redact_secrets("api_key=sk-1234abcd")
        assert "sk-1234abcd" not in result
        assert "REDACTED" in result


class TestShouldCapture:
    def test_empty_files_below_default_threshold(self):
        assert should_capture([]) is False

    def test_one_file_meets_default_threshold(self):
        assert should_capture(["auth.py"]) is True

    def test_multiple_files_meets_threshold(self):
        assert should_capture(["a.py", "b.py", "c.py"]) is True

    def test_zero_min_files_always_captures(self):
        assert should_capture([], min_files=0) is True

    def test_custom_threshold(self):
        assert should_capture(["a.py"], min_files=2) is False
        assert should_capture(["a.py", "b.py"], min_files=2) is True


class TestCaptureObservation:
    @pytest.fixture()
    def store(self, tmp_path):
        from memory.store import ObservationStore
        from storage_sqlite.database import Database

        db_path = tmp_path / "test.db"
        db = Database(db_path)
        db.initialize()
        store = ObservationStore(db)
        yield store
        db.close()

    def test_captures_observation_with_files(self, store):
        obs = Observation(
            summary="fixed auth bug",
            task_type="debug",
            files_touched=["auth.py"],
        )
        row_id = capture_observation(store, obs)
        assert row_id is not None
        assert isinstance(row_id, int)

    def test_skips_below_file_threshold(self, store):
        obs = Observation(summary="no files", task_type="general", files_touched=[])
        result = capture_observation(store, obs, min_files=1)
        assert result is None

    def test_captures_when_min_files_zero(self, store):
        obs = Observation(summary="no files allowed", task_type="handover")
        result = capture_observation(store, obs, min_files=0)
        assert result is not None

    def test_dedup_same_task_skipped(self, store):
        obs = Observation(
            summary="same task", task_type="debug", files_touched=["x.py"]
        )
        id1 = capture_observation(store, obs)
        obs2 = Observation(
            summary="same task", task_type="debug", files_touched=["y.py"]
        )
        id2 = capture_observation(store, obs2)
        assert id1 is not None
        assert id2 is None  # duplicate — same task_type + summary

    def test_different_task_type_not_deduped(self, store):
        obs1 = Observation(
            summary="same summary", task_type="debug", files_touched=["x.py"]
        )
        obs2 = Observation(
            summary="same summary", task_type="implement", files_touched=["x.py"]
        )
        id1 = capture_observation(store, obs1)
        id2 = capture_observation(store, obs2)
        assert id1 is not None
        assert id2 is not None

    def test_redacts_secrets_in_commands(self, store):
        obs = Observation(
            summary="deployed",
            task_type="commit",
            files_touched=["deploy.sh"],
            commands_run=["export TOKEN=supersecret && ./deploy.sh"],
        )
        row_id = capture_observation(store, obs, min_files=0)
        assert row_id is not None

        results = store.search("deployed")
        assert results
        assert "supersecret" not in str(results[0].commands_run)

    def test_task_hash_set_on_stored_observation(self, store):
        obs = Observation(
            summary="hash check",
            task_type="general",
            files_touched=["f.py"],
        )
        row_id = capture_observation(store, obs)
        assert row_id is not None
        results = store.search("hash check")
        assert results
        assert results[0].task_hash != ""
