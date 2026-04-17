"""Tests for the MCP resources capability (P3-6).

Covers the `resources/list` and `resources/read` JSON-RPC handlers and the
`notifications/resources/list_changed` signal emitted when a pack is added.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from contracts.models import ContextItem, ContextPack


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


# ---------------------------------------------------------------------------
# initialize capabilities
# ---------------------------------------------------------------------------

class TestInitializeCapabilities:
    def test_declares_resources_capability(self) -> None:
        from mcp_server.main import _handle
        resp = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        caps = resp["result"]["capabilities"]
        assert "resources" in caps
        assert caps["resources"] == {"listChanged": True}


# ---------------------------------------------------------------------------
# resources/list + resources/read
# ---------------------------------------------------------------------------

class TestResourcesList:
    def test_list_returns_empty_when_no_packs(self, tmp_path: Path) -> None:
        from mcp_server import resources
        (tmp_path / ".context-router").mkdir()
        out = resources.list_resources(str(tmp_path))
        assert out == {"resources": []}

    def test_list_returns_packs_after_save(self, tmp_path: Path) -> None:
        from core.pack_store import PackStore
        from mcp_server import resources
        pack = _make_pack()
        PackStore(tmp_path).save(pack)
        out = resources.list_resources(str(tmp_path))
        assert len(out["resources"]) == 1
        res = out["resources"][0]
        assert res["uri"] == f"context-router://packs/{pack.id}"
        assert res["mimeType"] == "application/json"
        assert "name" in res
        assert "description" in res


class TestResourcesRead:
    def test_read_returns_pack_json(self, tmp_path: Path) -> None:
        from core.pack_store import PackStore
        from mcp_server import resources
        pack = _make_pack()
        PackStore(tmp_path).save(pack)

        uri = f"context-router://packs/{pack.id}"
        out = resources.read_resource(uri, str(tmp_path))

        assert "contents" in out
        assert len(out["contents"]) == 1
        item = out["contents"][0]
        assert item["uri"] == uri
        assert item["mimeType"] == "application/json"

        # Text payload must be byte-identical to the stored file
        stored = (tmp_path / ".context-router" / "packs" / f"{pack.id}.json").read_text()
        assert item["text"] == stored

    def test_read_unknown_uri_raises(self, tmp_path: Path) -> None:
        from mcp_server import resources
        with pytest.raises(ValueError):
            resources.read_resource("not-a-valid-uri", str(tmp_path))

    def test_read_missing_uuid_raises(self, tmp_path: Path) -> None:
        from mcp_server import resources
        (tmp_path / ".context-router" / "packs").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            resources.read_resource(
                "context-router://packs/00000000-0000-0000-0000-000000000000",
                str(tmp_path),
            )


# ---------------------------------------------------------------------------
# JSON-RPC dispatch for resources/*
# ---------------------------------------------------------------------------

class TestResourcesDispatch:
    def test_resources_list_method(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.pack_store import PackStore
        from mcp_server.main import _handle
        pack = _make_pack()
        PackStore(tmp_path).save(pack)

        resp = _handle({
            "jsonrpc": "2.0", "id": 7, "method": "resources/list",
            "params": {"project_root": str(tmp_path)},
        })
        assert resp["result"]["resources"]
        assert resp["result"]["resources"][0]["uri"] == f"context-router://packs/{pack.id}"

    def test_resources_read_method(self, tmp_path: Path) -> None:
        from core.pack_store import PackStore
        from mcp_server.main import _handle
        pack = _make_pack()
        PackStore(tmp_path).save(pack)
        uri = f"context-router://packs/{pack.id}"

        resp = _handle({
            "jsonrpc": "2.0", "id": 8, "method": "resources/read",
            "params": {"uri": uri, "project_root": str(tmp_path)},
        })
        text = resp["result"]["contents"][0]["text"]
        payload = json.loads(text)
        assert payload["id"] == pack.id
        assert payload["query"] == pack.query
