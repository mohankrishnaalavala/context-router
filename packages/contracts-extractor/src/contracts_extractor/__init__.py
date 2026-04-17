"""context-router-contracts-extractor: OpenAPI/protobuf/GraphQL signature extraction.

This package walks a repository and returns signature-level contract
descriptors (endpoints, RPCs, operations) for use by cross-repo link
detection.  It does NOT validate requests/responses — see the ADR
"Contract extraction scope = signatures only" for rationale.
"""

from __future__ import annotations

from contracts_extractor.extractor import extract_contracts
from contracts_extractor.matching import (
    compile_endpoint_pattern,
    file_references_endpoint,
)
from contracts_extractor.models import (
    ApiEndpoint,
    Contract,
    GraphqlOperation,
    GrpcRpc,
    GrpcService,
)

__all__ = [
    "ApiEndpoint",
    "Contract",
    "GrpcRpc",
    "GrpcService",
    "GraphqlOperation",
    "compile_endpoint_pattern",
    "extract_contracts",
    "file_references_endpoint",
]
