"""Repo-level contract extractor facade.

Walks a repository, dispatches files to the right format parser, and
returns a flat list of ``Contract`` records for downstream consumers
(storage repositories, workspace link detection).
"""

from __future__ import annotations

from pathlib import Path

from contracts_extractor.models import Contract
from contracts_extractor.parsers import parse_graphql, parse_openapi, parse_protobuf

# Directories we never descend into — keeps walk cheap on large monorepos.
_SKIP_DIRS = frozenset({
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",
    ".context-router",
})

# Extension dispatch table.
_PROTO_EXTS = frozenset({".proto"})
_GRAPHQL_EXTS = frozenset({".graphql", ".gql"})
_OPENAPI_EXTS = frozenset({".yaml", ".yml", ".json"})

# Filename hints for OpenAPI — we still sniff the parsed doc for an
# "openapi"/"swagger" key, so false positives are cheap.
_OPENAPI_HINTS = ("openapi", "swagger", "api", "spec")


def _iter_files(root: Path):
    """Yield every file under *root*, skipping heavy/irrelevant directories."""
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIP_DIRS:
                    continue
                stack.append(entry)
            elif entry.is_file():
                yield entry


def _looks_like_openapi(name: str) -> bool:
    """Cheap filename heuristic to avoid parsing every yaml in the repo."""
    stem = name.lower()
    return any(hint in stem for hint in _OPENAPI_HINTS)


def extract_contracts(repo_path: Path) -> list[Contract]:
    """Walk *repo_path* and return every parsed contract found.

    Dispatch rules:
      * ``.proto``                → ``parse_protobuf``
      * ``.graphql`` / ``.gql``   → ``parse_graphql``
      * ``.yaml`` / ``.yml`` / ``.json`` whose filename hints at OpenAPI
        → ``parse_openapi``

    Args:
        repo_path: Repository root.

    Returns:
        Flat list of Contract records (mixed ApiEndpoint / GrpcService /
        GraphqlOperation).  Empty list if nothing is found.
    """
    if not repo_path.is_dir():
        return []

    contracts: list[Contract] = []

    for file_path in _iter_files(repo_path):
        suffix = file_path.suffix.lower()
        if suffix in _PROTO_EXTS:
            contracts.extend(parse_protobuf(file_path))
        elif suffix in _GRAPHQL_EXTS:
            contracts.extend(parse_graphql(file_path))
        elif suffix in _OPENAPI_EXTS and _looks_like_openapi(file_path.name):
            contracts.extend(parse_openapi(file_path))

    return contracts
