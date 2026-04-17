"""Dataclass models for extracted service contracts.

All contract parsers return these types; downstream consumers (workspace
link detector, storage repositories) depend on these shapes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


@dataclass(frozen=True)
class ApiEndpoint:
    """A single HTTP endpoint defined in an OpenAPI spec.

    Only signature-level data — we do NOT capture request / response
    schemas themselves, just references to them if present.
    """

    method: str                              # uppercase, e.g. "GET"
    path: str                                # e.g. "/users/{id}"
    operation_id: str = ""
    request_schema_ref: str = ""             # $ref string or empty
    response_schema_ref: str = ""
    source_file: str = ""
    line: int = 0


@dataclass(frozen=True)
class GrpcRpc:
    """A single RPC method inside a gRPC service."""

    name: str
    request_type: str
    response_type: str
    client_streaming: bool = False
    server_streaming: bool = False


@dataclass(frozen=True)
class GrpcService:
    """A gRPC service declaration parsed from a .proto file."""

    name: str
    rpcs: tuple[GrpcRpc, ...] = field(default_factory=tuple)
    messages: tuple[str, ...] = field(default_factory=tuple)
    source_file: str = ""
    line: int = 0


@dataclass(frozen=True)
class GraphqlOperation:
    """A GraphQL schema operation (query / mutation / subscription)."""

    name: str
    kind: Literal["query", "mutation", "subscription", "type", "input"]
    fields: tuple[str, ...] = field(default_factory=tuple)
    source_file: str = ""
    line: int = 0


# Union alias used by the extractor facade.
Contract = Union[ApiEndpoint, GrpcService, GraphqlOperation]
