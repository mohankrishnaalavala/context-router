from __future__ import annotations

import pytest
from workspace_store.store import CrossRepoEdge, RepoRecord, WorkspaceStore


@pytest.fixture
def store(tmp_path) -> WorkspaceStore:
    return WorkspaceStore.open(tmp_path / ".context-router" / "workspace.db")


class TestRegister:
    def test_register_new_repo(self, store, tmp_path):
        store.register_repo(
            RepoRecord(repo_id="r1", name="backend", root=str(tmp_path / "backend"))
        )
        assert store.get_repo("r1").name == "backend"

    def test_register_is_upsert(self, store):
        store.register_repo(RepoRecord(repo_id="r1", name="backend", root="/a"))
        store.register_repo(RepoRecord(repo_id="r1", name="backend", root="/b"))
        assert store.get_repo("r1").root == "/b"


class TestEdges:
    def test_write_and_read_edges(self, store):
        store.register_repo(RepoRecord(repo_id="r1", name="backend", root="/a"))
        store.register_repo(RepoRecord(repo_id="r2", name="frontend", root="/b"))
        edges = [CrossRepoEdge(
            src_repo_id="r1", src_symbol_id=None, src_file="ep.py",
            dst_repo_id="r2", dst_symbol_id=None, dst_file="client.ts",
            edge_kind="consumes_openapi", confidence=0.9,
        )]
        store.replace_edges_for_src("r1", edges)
        out = list(store.edges_from("r1"))
        assert len(out) == 1
        assert out[0].edge_kind == "consumes_openapi"

    def test_replace_is_scoped_to_src(self, store):
        store.register_repo(RepoRecord(repo_id="r1", name="a", root="/a"))
        store.register_repo(RepoRecord(repo_id="r2", name="b", root="/b"))
        store.replace_edges_for_src("r1", [CrossRepoEdge(
            src_repo_id="r1", src_symbol_id=None, src_file="x", dst_repo_id="r2",
            dst_symbol_id=None, dst_file="y", edge_kind="import", confidence=1.0,
        )])
        store.replace_edges_for_src("r2", [CrossRepoEdge(
            src_repo_id="r2", src_symbol_id=None, src_file="p", dst_repo_id="r1",
            dst_symbol_id=None, dst_file="q", edge_kind="import", confidence=1.0,
        )])
        store.replace_edges_for_src("r1", [])
        assert list(store.edges_from("r1")) == []
        assert len(list(store.edges_from("r2"))) == 1

    def test_edges_to_filters_by_dst(self, store):
        store.register_repo(RepoRecord(repo_id="r1", name="a", root="/a"))
        store.register_repo(RepoRecord(repo_id="r2", name="b", root="/b"))
        store.replace_edges_for_src("r1", [CrossRepoEdge(
            src_repo_id="r1", src_symbol_id=None, src_file="x", dst_repo_id="r2",
            dst_symbol_id=None, dst_file="y", edge_kind="import", confidence=1.0,
        )])
        assert len(list(store.edges_to("r2"))) == 1
        assert list(store.edges_to("r1")) == []
