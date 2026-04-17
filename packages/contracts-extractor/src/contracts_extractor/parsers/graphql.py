"""GraphQL SDL (.graphql / .gql) parser — regex-based, signatures only.

We walk top-level ``type Query { ... }``, ``type Mutation { ... }`` and
``type Subscription { ... }`` blocks to enumerate operations.  We also
capture bare ``type Foo``/``input Foo`` declarations for completeness.

No graphql-core dependency — the grammar we support is a subset of SDL
sufficient for signature extraction.
"""

from __future__ import annotations

import re
from pathlib import Path

from contracts_extractor.models import GraphqlOperation

# type Query { ... } / type Mutation { ... } / type Subscription { ... }
_ROOT_TYPE_RE = re.compile(
    r"(?P<kind>type|input)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{(?P<body>[^{}]*)\}",
    re.MULTILINE | re.DOTALL,
)

# field identifiers inside a type/input body (take leading identifier per line)
_FIELD_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*[(:]", re.MULTILINE)

_ROOTS = {"Query": "query", "Mutation": "mutation", "Subscription": "subscription"}


def _strip_comments(text: str) -> str:
    """Remove GraphQL # line comments; keep structure."""
    return re.sub(r"#[^\n]*", "", text)


def _line_of(text: str, pos: int) -> int:
    """Return 1-based line number of *pos* in *text*."""
    return text.count("\n", 0, pos) + 1


def parse_graphql(path: Path) -> list[GraphqlOperation]:
    """Parse a GraphQL schema file into a list of GraphqlOperation records.

    For the three "root" types (Query/Mutation/Subscription) every field
    becomes a separate GraphqlOperation with the appropriate ``kind``.  For
    other ``type`` / ``input`` blocks we emit a single operation whose
    ``fields`` tuple lists every field name.

    Args:
        path: Filesystem path to the .graphql / .gql file.

    Returns:
        List of GraphqlOperation records.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    text = _strip_comments(raw)

    ops: list[GraphqlOperation] = []
    source_file = str(path)

    for m in _ROOT_TYPE_RE.finditer(text):
        kind_kw = m.group("kind")           # "type" | "input"
        name = m.group("name")
        body = m.group("body") or ""
        line = _line_of(text, m.start())

        field_names = tuple(fm.group("name") for fm in _FIELD_RE.finditer(body))

        if kind_kw == "type" and name in _ROOTS:
            op_kind = _ROOTS[name]
            for field in field_names:
                ops.append(
                    GraphqlOperation(
                        name=field,
                        kind=op_kind,  # type: ignore[arg-type]
                        fields=(field,),
                        source_file=source_file,
                        line=line,
                    )
                )
        else:
            op_kind = "input" if kind_kw == "input" else "type"
            ops.append(
                GraphqlOperation(
                    name=name,
                    kind=op_kind,  # type: ignore[arg-type]
                    fields=field_names,
                    source_file=source_file,
                    line=line,
                )
            )

    return ops
