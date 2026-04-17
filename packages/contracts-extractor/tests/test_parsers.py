"""Unit tests for contract parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts_extractor.extractor import extract_contracts
from contracts_extractor.models import (
    ApiEndpoint,
    GraphqlOperation,
    GrpcService,
)
from contracts_extractor.parsers import (
    parse_graphql,
    parse_openapi,
    parse_protobuf,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------

class TestOpenAPI:
    def test_three_endpoints_parsed(self):
        endpoints = parse_openapi(FIXTURES / "sample-openapi.yaml")
        assert len(endpoints) == 3

    def test_get_user_by_id(self):
        endpoints = parse_openapi(FIXTURES / "sample-openapi.yaml")
        by_key = {(e.method, e.path): e for e in endpoints}
        ep = by_key["GET", "/users/{id}"]
        assert ep.operation_id == "getUserById"
        assert ep.response_schema_ref == "#/components/schemas/User"
        assert ep.request_schema_ref == ""

    def test_post_user_has_request_ref(self):
        endpoints = parse_openapi(FIXTURES / "sample-openapi.yaml")
        by_key = {(e.method, e.path): e for e in endpoints}
        ep = by_key["POST", "/users"]
        assert ep.operation_id == "createUser"
        assert ep.request_schema_ref == "#/components/schemas/User"

    def test_delete_has_no_refs(self):
        endpoints = parse_openapi(FIXTURES / "sample-openapi.yaml")
        by_key = {(e.method, e.path): e for e in endpoints}
        ep = by_key["DELETE", "/users/{id}"]
        assert ep.operation_id == "deleteUser"
        assert ep.request_schema_ref == ""

    def test_invalid_spec_returns_empty(self, tmp_path):
        bad = tmp_path / "not-openapi.yaml"
        bad.write_text("just: some yaml\n")
        assert parse_openapi(bad) == []

    def test_json_spec(self, tmp_path):
        import json
        spec = {
            "openapi": "3.0.0",
            "paths": {
                "/ping": {"get": {"operationId": "ping", "responses": {"200": {}}}}
            },
        }
        path = tmp_path / "openapi.json"
        path.write_text(json.dumps(spec))
        endpoints = parse_openapi(path)
        assert len(endpoints) == 1
        assert endpoints[0].method == "GET"
        assert endpoints[0].path == "/ping"


# ---------------------------------------------------------------------------
# Protobuf
# ---------------------------------------------------------------------------

class TestProtobuf:
    def test_one_service_two_rpcs(self):
        services = parse_protobuf(FIXTURES / "sample.proto")
        assert len(services) == 1
        svc = services[0]
        assert svc.name == "Greeter"
        assert len(svc.rpcs) == 2

    def test_rpc_signatures(self):
        svc = parse_protobuf(FIXTURES / "sample.proto")[0]
        by_name = {r.name: r for r in svc.rpcs}
        hello = by_name["SayHello"]
        assert hello.request_type == "HelloRequest"
        assert hello.response_type == "HelloReply"
        assert not hello.client_streaming
        assert not hello.server_streaming

        bye = by_name["SayGoodbye"]
        assert bye.server_streaming is True
        assert bye.client_streaming is False

    def test_messages_collected(self):
        svc = parse_protobuf(FIXTURES / "sample.proto")[0]
        assert "HelloRequest" in svc.messages
        assert "HelloReply" in svc.messages

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "empty.proto"
        p.write_text("")
        assert parse_protobuf(p) == []


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------

class TestGraphQL:
    def test_query_and_mutation_operations(self):
        ops = parse_graphql(FIXTURES / "sample.graphql")
        kinds = {op.kind for op in ops}
        assert "query" in kinds
        assert "mutation" in kinds

    def test_query_name_captured(self):
        ops = parse_graphql(FIXTURES / "sample.graphql")
        queries = [op for op in ops if op.kind == "query"]
        assert any(op.name == "user" for op in queries)

    def test_mutation_name_captured(self):
        ops = parse_graphql(FIXTURES / "sample.graphql")
        mutations = [op for op in ops if op.kind == "mutation"]
        assert any(op.name == "createUser" for op in mutations)

    def test_object_type_captured(self):
        ops = parse_graphql(FIXTURES / "sample.graphql")
        types = [op for op in ops if op.kind == "type"]
        assert any(op.name == "User" for op in types)


# ---------------------------------------------------------------------------
# Extractor facade
# ---------------------------------------------------------------------------

class TestExtractor:
    def test_walks_fixtures_dir(self, tmp_path):
        # Copy fixtures into a scratch repo layout
        import shutil
        (tmp_path / "api").mkdir()
        (tmp_path / "proto").mkdir()
        (tmp_path / "graph").mkdir()
        shutil.copy(FIXTURES / "sample-openapi.yaml", tmp_path / "api" / "openapi.yaml")
        shutil.copy(FIXTURES / "sample.proto", tmp_path / "proto" / "service.proto")
        shutil.copy(FIXTURES / "sample.graphql", tmp_path / "graph" / "schema.graphql")

        contracts = extract_contracts(tmp_path)
        has_api = any(isinstance(c, ApiEndpoint) for c in contracts)
        has_grpc = any(isinstance(c, GrpcService) for c in contracts)
        has_gql = any(isinstance(c, GraphqlOperation) for c in contracts)
        assert has_api
        assert has_grpc
        assert has_gql

    def test_skips_node_modules(self, tmp_path):
        import shutil
        node_mods = tmp_path / "node_modules" / "foo"
        node_mods.mkdir(parents=True)
        shutil.copy(FIXTURES / "sample.proto", node_mods / "x.proto")
        assert extract_contracts(tmp_path) == []

    def test_missing_dir(self, tmp_path):
        assert extract_contracts(tmp_path / "does-not-exist") == []
