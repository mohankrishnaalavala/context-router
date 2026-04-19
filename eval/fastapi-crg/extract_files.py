"""File-path extraction for CR and CRG eval JSON outputs.

Mirrors the judge's patched ``compute_metrics.py`` in the reference eval at
``/Users/mohankrishnaalavala/Documents/project_context/fastapi/.eval_results/``:

  - ``extract_cr_files``  reads ``selected_items[].path_or_ref`` and strips the
    project-root prefix so paths become repo-relative.
  - ``extract_crg_files`` reads, in order:
        ``changed_functions[].file_path``
        ``test_gaps[].file``
        ``review_priorities[].file_path``
        ``affected_flows[].file_path``

Neither function raises on schema drift; missing keys produce an empty set.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Set


def _strip_prefix(path: str, project_root: str | None) -> str:
    """Return ``path`` made relative to ``project_root`` (best-effort).

    Accepts absolute or already-relative paths. Normalises separators and
    trims leading ``./`` so downstream set-comparison against ground-truth
    paths from ``tasks.yaml`` is consistent.
    """
    if not path:
        return ""
    # Normalise so comparisons are platform-stable.
    p = path.replace("\\", "/")
    if project_root:
        root = project_root.replace("\\", "/").rstrip("/")
        if p.startswith(root + "/"):
            p = p[len(root) + 1 :]
    if p.startswith("./"):
        p = p[2:]
    return p


def _collect_paths(items: Iterable[Any], *, keys: list[str]) -> list[str]:
    """Pull the first non-empty value from each dict under any of ``keys``."""
    out: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for k in keys:
            v = item.get(k)
            if isinstance(v, str) and v:
                out.append(v)
                break
    return out


def extract_cr_files(pack: dict[str, Any], project_root: str | None = None) -> Set[str]:
    """Return the set of repo-relative file paths surfaced by context-router.

    The CR pack schema uses ``selected_items[].path_or_ref`` (absolute path
    on disk). Other historical keys like ``file`` / ``file_path`` are also
    checked defensively so old fixtures still parse.
    """
    items = pack.get("selected_items") or pack.get("items") or []
    raw = _collect_paths(items, keys=["path_or_ref", "file_path", "file", "path"])
    out: Set[str] = set()
    for p in raw:
        rel = _strip_prefix(p, project_root)
        if rel:
            out.add(rel)
    return out


def extract_crg_files(payload: dict[str, Any], project_root: str | None = None) -> Set[str]:
    """Return the set of repo-relative file paths surfaced by code-review-graph.

    CRG's ``detect-changes`` JSON lists file paths under four sibling keys:
        changed_functions[].file_path
        test_gaps[].file
        review_priorities[].file_path
        affected_flows[].file_path
    """
    buckets: list[str] = []
    buckets.extend(_collect_paths(payload.get("changed_functions"), keys=["file_path", "file"]))
    buckets.extend(_collect_paths(payload.get("test_gaps"), keys=["file", "file_path"]))
    buckets.extend(_collect_paths(payload.get("review_priorities"), keys=["file_path", "file"]))
    buckets.extend(_collect_paths(payload.get("affected_flows"), keys=["file_path", "file"]))
    out: Set[str] = set()
    for p in buckets:
        rel = _strip_prefix(p, project_root)
        if rel:
            out.add(rel)
    return out


__all__ = ["extract_cr_files", "extract_crg_files"]
