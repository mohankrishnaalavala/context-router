"""Per-format parsers for service contracts."""

from __future__ import annotations

from contracts_extractor.parsers.graphql import parse_graphql
from contracts_extractor.parsers.openapi import parse_openapi
from contracts_extractor.parsers.protobuf import parse_protobuf

__all__ = ["parse_openapi", "parse_protobuf", "parse_graphql"]
