"""Tests for ContractRepository (migration 0011)."""

from __future__ import annotations

from pathlib import Path

import pytest

from storage_sqlite.database import Database
from storage_sqlite.repositories import ContractRepository


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "contracts.db")
    database.initialize()
    return database


class TestApiEndpoint:
    def test_upsert_and_list(self, db: Database):
        repo = ContractRepository(db.connection)
        repo.upsert_api_endpoint(
            repo="svc-a", method="get", path="/users/{id}",
            operation_id="getUserById",
            source_file="openapi.yaml", line=5,
        )
        rows = repo.list_api_endpoints("svc-a")
        assert len(rows) == 1
        assert rows[0]["method"] == "GET"        # upper-cased on insert
        assert rows[0]["path"] == "/users/{id}"
        assert rows[0]["operation_id"] == "getUserById"

    def test_upsert_is_idempotent(self, db: Database):
        repo = ContractRepository(db.connection)
        for _ in range(3):
            repo.upsert_api_endpoint(
                repo="svc-a", method="GET", path="/ping", operation_id="ping",
            )
        rows = repo.list_api_endpoints("svc-a")
        assert len(rows) == 1

    def test_list_isolates_repos(self, db: Database):
        repo = ContractRepository(db.connection)
        repo.upsert_api_endpoint(repo="svc-a", method="GET", path="/a")
        repo.upsert_api_endpoint(repo="svc-b", method="GET", path="/b")
        assert [r["path"] for r in repo.list_api_endpoints("svc-a")] == ["/a"]
        assert [r["path"] for r in repo.list_api_endpoints("svc-b")] == ["/b"]


class TestGrpc:
    def test_upsert_and_list(self, db: Database):
        repo = ContractRepository(db.connection)
        repo.upsert_grpc(
            repo="svc-g", service="Greeter", rpc="Say",
            request_type="Req", response_type="Resp",
            source_file="a.proto", line=10,
        )
        rows = repo.list_grpc("svc-g")
        assert len(rows) == 1
        assert rows[0]["service"] == "Greeter"
        assert rows[0]["rpc"] == "Say"
        assert rows[0]["request_type"] == "Req"
        assert rows[0]["response_type"] == "Resp"


class TestGraphql:
    def test_upsert_and_list(self, db: Database):
        repo = ContractRepository(db.connection)
        repo.upsert_graphql(repo="svc-q", name="user", kind="query")
        repo.upsert_graphql(repo="svc-q", name="createUser", kind="mutation")
        rows = repo.list_graphql("svc-q")
        names = {r["name"] for r in rows}
        assert names == {"user", "createUser"}
