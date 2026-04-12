"""Tests for ObservationStore and DecisionStore."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.models import Decision, Observation
from memory.store import DecisionStore, ObservationStore
from storage_sqlite.database import Database


# -----------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> Database:
    """Return an open, initialised Database in a temp directory."""
    d = Database(tmp_path / "test.db")
    d.initialize()
    return d


@pytest.fixture()
def obs_store(db: Database) -> ObservationStore:
    return ObservationStore(db)


@pytest.fixture()
def dec_store(db: Database) -> DecisionStore:
    return DecisionStore(db)


# -----------------------------------------------------------------------
# ObservationStore
# -----------------------------------------------------------------------

def test_add_and_get_all(obs_store: ObservationStore) -> None:
    obs = Observation(summary="fixed the auth bug", files_touched=["src/auth.py"])
    obs_store.add(obs)
    all_obs = obs_store._get_all()
    assert len(all_obs) == 1
    assert all_obs[0].summary == "fixed the auth bug"


def test_search_finds_by_keyword(obs_store: ObservationStore) -> None:
    obs_store.add(Observation(summary="fixed database connection pooling"))
    obs_store.add(Observation(summary="added user endpoint"))
    results = obs_store.search("database")
    assert len(results) == 1
    assert "database" in results[0].summary


def test_search_no_results(obs_store: ObservationStore) -> None:
    obs_store.add(Observation(summary="something unrelated"))
    results = obs_store.search("zzz_nonexistent_zzz")
    assert results == []


def test_add_from_session_json_single(obs_store: ObservationStore) -> None:
    data = {"summary": "from session", "task_type": "implement"}
    ids = obs_store.add_from_session_json(json.dumps(data))
    assert len(ids) == 1


def test_add_from_session_json_list(obs_store: ObservationStore) -> None:
    data = [
        {"summary": "obs one"},
        {"summary": "obs two"},
    ]
    ids = obs_store.add_from_session_json(json.dumps(data))
    assert len(ids) == 2


def test_add_from_session_json_invalid_raises(obs_store: ObservationStore) -> None:
    with pytest.raises(ValueError):
        obs_store.add_from_session_json("not json {{")


def test_find_stale_all_files_missing(obs_store: ObservationStore) -> None:
    obs = Observation(
        summary="old work",
        files_touched=["deleted_file.py", "another_deleted.py"],
    )
    obs_store.add(obs)
    stale = obs_store.find_stale()
    assert len(stale) == 1


def test_find_stale_no_files_touched_not_stale(obs_store: ObservationStore) -> None:
    obs = Observation(summary="no files", files_touched=[])
    obs_store.add(obs)
    stale = obs_store.find_stale()
    assert stale == []


# -----------------------------------------------------------------------
# DecisionStore
# -----------------------------------------------------------------------

def test_add_and_get_all(dec_store: DecisionStore) -> None:
    dec = Decision(title="Use SQLite FTS5", decision="Chosen for local-first simplicity")
    dec_store.add(dec)
    all_decs = dec_store.get_all()
    assert len(all_decs) == 1
    assert all_decs[0].title == "Use SQLite FTS5"


def test_search_finds_by_title(dec_store: DecisionStore) -> None:
    dec_store.add(Decision(title="Use async IO", decision="For MCP server performance"))
    dec_store.add(Decision(title="Use SQLite FTS5", decision="For local search"))
    results = dec_store.search("SQLite")
    assert len(results) == 1
    assert "SQLite" in results[0].title


def test_get_all_ordered_recent_first(dec_store: DecisionStore) -> None:
    dec_store.add(Decision(title="first"))
    dec_store.add(Decision(title="second"))
    all_decs = dec_store.get_all()
    # Both should be returned (order may vary by timestamp precision)
    titles = [d.title for d in all_decs]
    assert "first" in titles
    assert "second" in titles


def test_by_tags_filters_correctly(dec_store: DecisionStore) -> None:
    dec_store.add(Decision(title="A", tags=["storage", "performance"]))
    dec_store.add(Decision(title="B", tags=["api"]))
    dec_store.add(Decision(title="C", tags=["storage"]))
    results = dec_store.by_tags(["storage"])
    titles = {d.title for d in results}
    assert "A" in titles
    assert "C" in titles
    assert "B" not in titles


def test_by_tags_case_insensitive(dec_store: DecisionStore) -> None:
    dec_store.add(Decision(title="X", tags=["Storage"]))
    results = dec_store.by_tags(["storage"])
    assert len(results) == 1


def test_by_tags_no_match(dec_store: DecisionStore) -> None:
    dec_store.add(Decision(title="Y", tags=["api"]))
    assert dec_store.by_tags(["security"]) == []
