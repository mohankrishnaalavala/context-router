"""Cross-repo link auto-detection from Python import statements."""

from __future__ import annotations

import re
from pathlib import Path

from contracts.models import RepoDescriptor

# Match "import <name>" or "from <name>" at the start of a line
_IMPORT_PATTERN = re.compile(
    r"^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
    re.MULTILINE,
)


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
