from __future__ import annotations

import sqlite3

import pytest
from workspace.reconcile import reconcile_repo
from workspace.store import RepoRecord, WorkspaceStore


@pytest.fixture
def workspace_layout(tmp_path):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    backend.mkdir()
    frontend.mkdir()

    backend_db = backend / ".context-router" / "context-router.db"
    backend_db.parent.mkdir(parents=True)
    con = sqlite3.connect(backend_db)
    con.execute(
        "CREATE TABLE api_endpoints("
        "id INTEGER PRIMARY KEY,repo TEXT,method TEXT,path TEXT,"
        "operation_id TEXT,source_file TEXT,line INTEGER)"
    )
    con.execute(
        "INSERT INTO api_endpoints(repo,method,path,operation_id,source_file,line) "
        "VALUES('backend','GET','/foo','getFoo','backend.py',1)"
    )
    con.commit()
    con.close()

    client = frontend / "src" / "client.ts"
    client.parent.mkdir()
    client.write_text('export const f = () => fetch("/foo");\n')

    store = WorkspaceStore.open(tmp_path / ".context-router" / "workspace.db")
    store.register_repo(RepoRecord(repo_id="rb", name="backend", root=str(backend)))
    store.register_repo(RepoRecord(repo_id="rf", name="frontend", root=str(frontend)))
    return {"store": store, "backend": backend, "frontend": frontend, "tmp": tmp_path}


class TestReconcile:
    def test_reconcile_frontend_finds_consumes_edge(self, workspace_layout):
        store = workspace_layout["store"]
        n = reconcile_repo(
            store,
            repo_id="rf",
            repo_root=workspace_layout["frontend"],
            sibling_repos=[("rb", workspace_layout["backend"])],
        )
        assert n == 1
        edges = list(store.edges_from("rf"))
        assert len(edges) == 1
        assert edges[0].edge_kind == "consumes_openapi"
        assert edges[0].dst_repo_id == "rb"

    def test_reconcile_is_idempotent(self, workspace_layout):
        store = workspace_layout["store"]
        reconcile_repo(
            store,
            repo_id="rf",
            repo_root=workspace_layout["frontend"],
            sibling_repos=[("rb", workspace_layout["backend"])],
        )
        n2 = reconcile_repo(
            store,
            repo_id="rf",
            repo_root=workspace_layout["frontend"],
            sibling_repos=[("rb", workspace_layout["backend"])],
        )
        assert n2 == 1
        assert len(list(store.edges_from("rf"))) == 1
