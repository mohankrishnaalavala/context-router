"""Protobuf (.proto) parser — regex-based, signatures only.

We extract service + rpc signatures via lightweight regex.  We intentionally
avoid a grpc-tools / protoc dependency: the goal is only to identify
cross-repo consumers, not to round-trip wire formats.
"""

from __future__ import annotations

import re
from pathlib import Path

from contracts_extractor.models import GrpcRpc, GrpcService

# service Foo { ... }
_SERVICE_RE = re.compile(
    r"service\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{(?P<body>[^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
    re.MULTILINE | re.DOTALL,
)

# rpc Foo(Req) returns (Resp);  — also handles `stream` on either side.
_RPC_RE = re.compile(
    r"rpc\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\(\s*(?P<cstream>stream\s+)?(?P<req>[A-Za-z_][\w.]*)\s*\)\s*"
    r"returns\s*"
    r"\(\s*(?P<sstream>stream\s+)?(?P<resp>[A-Za-z_][\w.]*)\s*\)\s*[;{]",
    re.MULTILINE | re.DOTALL,
)

# message Foo { ... }
_MESSAGE_RE = re.compile(
    r"message\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\{",
    re.MULTILINE,
)


def _strip_comments(text: str) -> str:
    """Remove // line and /* block */ comments.

    Keeps strings intact well enough for signature extraction (proto strings
    rarely contain /* or //).
    """
    # block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # line comments (keep the newline)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _line_of(text: str, pos: int) -> int:
    """Return 1-based line number of *pos* in *text*."""
    return text.count("\n", 0, pos) + 1


def parse_protobuf(path: Path) -> list[GrpcService]:
    """Parse a ``.proto`` file into a list of GrpcService records.

    Args:
        path: Filesystem path to the .proto file.

    Returns:
        List of GrpcService records (one per ``service`` block).  Returns
        an empty list if the file is unreadable or contains no services.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    text = _strip_comments(raw)

    # Messages are file-level and may be referenced from any service.
    messages: list[str] = [m.group("name") for m in _MESSAGE_RE.finditer(text)]
    messages_tuple = tuple(messages)

    services: list[GrpcService] = []
    for svc_match in _SERVICE_RE.finditer(text):
        name = svc_match.group("name")
        body = svc_match.group("body") or ""
        line = _line_of(text, svc_match.start())

        rpcs: list[GrpcRpc] = []
        for rpc_match in _RPC_RE.finditer(body):
            rpcs.append(
                GrpcRpc(
                    name=rpc_match.group("name"),
                    request_type=rpc_match.group("req"),
                    response_type=rpc_match.group("resp"),
                    client_streaming=bool(rpc_match.group("cstream")),
                    server_streaming=bool(rpc_match.group("sstream")),
                )
            )

        services.append(
            GrpcService(
                name=name,
                rpcs=tuple(rpcs),
                messages=messages_tuple,
                source_file=str(path),
                line=line,
            )
        )

    return services
