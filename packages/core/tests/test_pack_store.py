"""Tests for PackStore — the on-disk registry of generated ContextPacks."""

from __future__ import annotations

import json
from pathlib import Path

from contracts.models import ContextItem, ContextPack
from core.pack_store import PackStore


def _make_pack(query: str = "hello", mode: str = "implement") -> ContextPack:
    return ContextPack(
        mode=mode,
        query=query,
        selected_items=[
            ContextItem(
                source_type="code",
                repo="demo",
                path_or_ref="src/main.py",
                title="main",
                reason="entry point",
                confidence=0.9,
                est_tokens=42,
            )
        ],
        total_est_tokens=42,
        baseline_est_tokens=100,
        reduction_pct=58.0,
    )


class TestSaveAndList:
    def test_save_creates_uuid_file(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        pack = _make_pack()
        entry = store.save(pack)
        assert entry["uuid"] == pack.id
        pack_file = tmp_path / ".context-router" / "packs" / f"{pack.id}.json"
        assert pack_file.exists()
        # Byte-for-byte identical to the pack's canonical JSON form
        assert pack_file.read_text() == pack.model_dump_json(indent=2)

    def test_save_updates_index_newest_first(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        a = _make_pack(query="a")
        b = _make_pack(query="b")
        store.save(a)
        store.save(b)
        listed = store.list()
        assert [e["uuid"] for e in listed] == [b.id, a.id]
        # Each entry carries the minimal metadata fields
        for entry in listed:
            assert set(entry.keys()) >= {"uuid", "mode", "query", "created_at", "tokens"}

    def test_list_empty_when_no_packs(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        assert store.list() == []


class TestGet:
    def test_get_returns_stored_pack(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        pack = _make_pack()
        store.save(pack)
        got = store.get(pack.id)
        assert got is not None
        assert got.id == pack.id
        assert got.query == pack.query

    def test_get_returns_none_for_missing_uuid(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        assert store.get("00000000-0000-0000-0000-000000000000") is None


class TestDelete:
    def test_delete_removes_file_and_index_entry(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        pack = _make_pack()
        store.save(pack)
        assert store.delete(pack.id) is True
        assert store.get(pack.id) is None
        assert store.list() == []
        assert not (tmp_path / ".context-router" / "packs" / f"{pack.id}.json").exists()

    def test_delete_returns_false_for_missing(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        assert store.delete("no-such-uuid") is False


class TestLRUEviction:
    def test_twentyfirst_save_evicts_oldest(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        saved_ids: list[str] = []
        for i in range(21):
            pack = _make_pack(query=f"q{i}")
            store.save(pack)
            saved_ids.append(pack.id)

        listed = store.list()
        assert len(listed) == 20
        # Newest (saved_ids[20]) is first; oldest (saved_ids[0]) should be evicted
        assert listed[0]["uuid"] == saved_ids[20]
        remaining_ids = {e["uuid"] for e in listed}
        assert saved_ids[0] not in remaining_ids
        # Files for evicted packs are cleaned up
        evicted_file = tmp_path / ".context-router" / "packs" / f"{saved_ids[0]}.json"
        assert not evicted_file.exists()


class TestIndexFile:
    def test_index_json_is_wellformed(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        store.save(_make_pack())
        index_path = tmp_path / ".context-router" / "packs" / "index.json"
        assert index_path.exists()
        data = json.loads(index_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1

    def test_save_updates_gitignore(self, tmp_path: Path) -> None:
        store = PackStore(tmp_path)
        store.save(_make_pack())
        gitignore = tmp_path / ".context-router" / ".gitignore"
        assert gitignore.exists()
        assert "packs/" in gitignore.read_text()
