"""Cross-repo link auto-detection.

Two independent detectors share this module:

1. **Python-import detector** (original).  Scans ``*.py`` files for
   ``import <repo>`` / ``from <repo>`` and returns a plain
   ``{source: [targets]}`` mapping.  Kept for back-compat.
2. **Contract detector** (new).  For every repo that exposes OpenAPI
   endpoints, scans the *other* repos' source files for HTTP-client calls
   matching those paths and emits a ``ContractLink`` of kind ``consumes``.

Both detectors are signature-only — they never execute or validate
requests.  See the ADR "Contract extraction scope = signatures only".
"""

from __future__ import annotations

import re
from pathlib import Path

from contracts.models import ContractLink, RepoDescriptor
from contracts_extractor import extract_contracts
from contracts_extractor.models import ApiEndpoint

# Match "import <name>" or "from <name>" at the start of a line
_IMPORT_PATTERN = re.compile(
    r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.MULTILINE,
)

# File extensions we scan for HTTP client calls.
_CLIENT_EXTS = frozenset({
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".java", ".kt", ".rb", ".cs",
    ".rs", ".php", ".mjs", ".cjs",
})

# Directories we always skip when scanning for HTTP calls.
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv",
    "__pycache__", "dist", "build", ".tox", "target",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".context-router",
})


def detect_links(repos: list[RepoDescriptor]) -> dict[str, list[str]]:
    """Auto-detect cross-repo links by scanning Python import statements.

    For each pair of repos (A, B): if any .py file in repo A contains
    ``import <B-name>`` or ``from <B-name>`` (where <B-name> is B's repo
    name with hyphens replaced by underscores), then A → B is recorded as
    a link.

    Args:
        repos: List of repo descriptors to scan.

    Returns:
        Dict ``{repo_name: [linked_repo_name, ...]}``.  Only repos with
        at least one detected link appear as keys.
    """
    # Build name → repo map; normalise names to Python identifiers
    name_map: dict[str, str] = {}
    for repo in repos:
        py_name = repo.name.replace("-", "_").replace(" ", "_").lower()
        name_map[py_name] = repo.name

    links: dict[str, list[str]] = {}

    for repo in repos:
        if not repo.path.is_dir():
            continue

        detected: set[str] = set()
        for py_file in repo.path.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for m in _IMPORT_PATTERN.finditer(text):
                imported_base = m.group(1).lower()
                if imported_base in name_map:
                    target = name_map[imported_base]
                    if target != repo.name:  # don't self-link
                        detected.add(target)

        if detected:
            links[repo.name] = sorted(detected)

    return links


# ---------------------------------------------------------------------------
# Contract-based detector
# ---------------------------------------------------------------------------

def _path_to_regex(openapi_path: str) -> re.Pattern[str]:
    """Convert an OpenAPI path template to a regex matching URL literals.

    ``/users/{id}`` → matches ``/users/123``, ``/users/abc``, ``/users/{id}``.

    Matches occur when the path appears inside a string literal (single,
    double or back-quote) preceded by common HTTP-client markers (``fetch``,
    ``axios``, ``requests``, ``http.Get``) OR simply as a substring — we
    prefer recall over precision for signature-only discovery.
    """
    # Escape the path, then replace the escaped {param} segments with a
    # permissive character class.
    escaped = re.escape(openapi_path)
    # After escape, ``{id}`` looks like ``\{id\}``; replace back.
    regex = re.sub(r"\\\{[^}]+\\\}", r"[^/\\s\"'`)]+", escaped)
    # Allow either the concrete URL or the literal OpenAPI template form.
    # Wrap in a non-capturing group with quote/back-tick delimiters to avoid
    # matching arbitrary substrings (e.g. "/users" in a log line).
    return re.compile(rf"""["'`]{regex}(?:["'`?/])""")


def _iter_source_files(root: Path):
    """Yield every source file in *root* that we might search for HTTP calls."""
    stack: list[Path] = [root]
    while stack:
        cur = stack.pop()
        try:
            entries = list(cur.iterdir())
        except (OSError, PermissionError):
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIP_DIRS:
                    continue
                stack.append(entry)
            elif entry.is_file() and entry.suffix.lower() in _CLIENT_EXTS:
                yield entry


def detect_contract_links(repos: list[RepoDescriptor]) -> list[ContractLink]:
    """Infer ``consumes`` links across repos from real contracts.

    Algorithm:
      1. For each repo A, run ``extract_contracts`` to collect the
         OpenAPI endpoints A **exposes**.
      2. For each other repo B, scan B's source files; if any line contains
         a URL literal whose path matches one of A's endpoint paths, emit
         ``ContractLink(from_repo=B, to_repo=A, kind="consumes",
         endpoint={"method": <M>, "path": <P>})``.

    We keep matching loose on purpose — the link graph is advisory, not
    authoritative.  Duplicates across files are de-duped.

    Args:
        repos: Workspace repo descriptors.

    Returns:
        List of distinct ContractLink records.
    """
    # Step 1: build endpoint index per repo (only ApiEndpoint for now).
    endpoints_by_repo: dict[str, list[ApiEndpoint]] = {}
    for repo in repos:
        if not repo.path.is_dir():
            continue
        contracts = extract_contracts(repo.path)
        eps = [c for c in contracts if isinstance(c, ApiEndpoint)]
        if eps:
            endpoints_by_repo[repo.name] = eps

    if not endpoints_by_repo:
        return []

    # Pre-compile regex per endpoint.  Dedupe identical paths — the match
    # yields the owner repo; method is carried separately.
    compiled: list[tuple[str, str, str, re.Pattern[str]]] = []  # (repo, method, path, re)
    seen: set[tuple[str, str, str]] = set()
    for owner_repo, eps in endpoints_by_repo.items():
        for ep in eps:
            key = (owner_repo, ep.method, ep.path)
            if key in seen:
                continue
            seen.add(key)
            compiled.append((owner_repo, ep.method, ep.path, _path_to_regex(ep.path)))

    # Step 2: scan consumer repos for matches.
    links: list[ContractLink] = []
    emitted: set[tuple[str, str, str, str]] = set()

    for consumer in repos:
        if not consumer.path.is_dir():
            continue
        for src_file in _iter_source_files(consumer.path):
            try:
                text = src_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if not text:
                continue

            for owner_repo, method, path, pattern in compiled:
                if owner_repo == consumer.name:
                    continue  # never self-link
                if pattern.search(text) is None:
                    continue
                key = (consumer.name, owner_repo, method, path)
                if key in emitted:
                    continue
                emitted.add(key)
                links.append(
                    ContractLink(
                        from_repo=consumer.name,
                        to_repo=owner_repo,
                        kind="consumes",
                        endpoint={"method": method, "path": path},
                    )
                )

    # Sort for deterministic output.
    links.sort(key=lambda cl: (cl.from_repo, cl.to_repo, cl.endpoint.get("path", "")))
    return links
