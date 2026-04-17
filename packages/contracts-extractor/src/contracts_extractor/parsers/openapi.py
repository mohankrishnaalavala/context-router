"""OpenAPI 3.x spec parser.

Extracts signature-level ApiEndpoint records from a .yaml / .json spec.
We intentionally do NOT validate requests or responses; we only walk the
``paths`` block and the verb nodes under each path.

Parsing uses PyYAML (already a repo dependency) plus the stdlib ``json``
module — no heavy spec-validator dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from contracts_extractor.models import ApiEndpoint

_HTTP_METHODS = frozenset({
    "get", "put", "post", "delete", "options", "head", "patch", "trace",
})


def _load(path: Path) -> Any:
    """Load YAML/JSON from *path*.  Returns None on failure or empty."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(text)
        # Default: YAML (also accepts JSON, since JSON is valid YAML).
        return yaml.safe_load(text)
    except (yaml.YAMLError, json.JSONDecodeError):
        return None


def _ref_str(schema: Any) -> str:
    """Pull a $ref string out of a schema-ish value, or return empty."""
    if not isinstance(schema, dict):
        return ""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return ref
    # Walk common nested shapes: {content: {"application/json": {schema: {...}}}}
    content = schema.get("content")
    if isinstance(content, dict):
        for media in content.values():
            if isinstance(media, dict):
                inner = media.get("schema")
                if isinstance(inner, dict):
                    nested = _ref_str(inner)
                    if nested:
                        return nested
    return ""


def parse_openapi(path: Path) -> list[ApiEndpoint]:
    """Parse an OpenAPI 3.x spec file into a list of ApiEndpoint records.

    Args:
        path: Filesystem path to the spec.

    Returns:
        List of ApiEndpoint records — empty if the file is not a recognisable
        OpenAPI document.
    """
    doc = _load(path)
    if not isinstance(doc, dict):
        return []

    # Accept both "openapi" (3.x) and "swagger" (2.x) root keys.  We only
    # guarantee 3.x coverage, but 2.x has the same paths shape for signatures.
    if "openapi" not in doc and "swagger" not in doc:
        return []

    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return []

    endpoints: list[ApiEndpoint] = []
    source_file = str(path)

    for route, verbs in paths.items():
        if not isinstance(verbs, dict) or not isinstance(route, str):
            continue
        for method, op in verbs.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            if not isinstance(op, dict):
                continue

            op_id = op.get("operationId", "") or ""

            req_ref = _ref_str(op.get("requestBody"))

            resp_ref = ""
            responses = op.get("responses")
            if isinstance(responses, dict):
                # Prefer 200-ish responses, then fall through.
                ordered_codes = sorted(
                    responses.keys(),
                    key=lambda k: (0 if str(k).startswith("2") else 1, str(k)),
                )
                for code in ordered_codes:
                    resp_ref = _ref_str(responses.get(code))
                    if resp_ref:
                        break

            endpoints.append(
                ApiEndpoint(
                    method=method.upper(),
                    path=route,
                    operation_id=str(op_id),
                    request_schema_ref=req_ref,
                    response_schema_ref=resp_ref,
                    source_file=source_file,
                    line=0,  # YAML line info not cheap to recover; keep 0.
                )
            )

    return endpoints
