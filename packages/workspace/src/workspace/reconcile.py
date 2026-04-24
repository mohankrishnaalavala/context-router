"""Per-repo reconcile pass: re-derive src_repo_id edges from the repo's own DB."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from workspace_store.store import CrossRepoEdge, WorkspaceStore


def _per_repo_db_path(repo_root: Path) -> Path:
    return repo_root / ".context-router" / "context-router.db"


def _sibling_endpoints(
    sibling_repos: list[tuple[str, Path]],
) -> list[tuple[str, str, str, str]]:
    """Return (sibling_repo_id, method, path, source_file) from each sibling's api_endpoints."""
    out: list[tuple[str, str, str, str]] = []
    for repo_id, root in sibling_repos:
        db = _per_repo_db_path(root)
        if not db.exists():
            continue
        con = sqlite3.connect(db)
        try:
            try:
                rows = con.execute(
                    "SELECT method, path, source_file FROM api_endpoints"
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            for method, path, source_file in rows:
                out.append((repo_id, method, path, source_file or ""))
        finally:
            con.close()
    return out


def _scan_source_files(root: Path):
    for ext in (".ts", ".tsx", ".js", ".jsx", ".py", ".java", ".cs"):
        for p in root.rglob(f"*{ext}"):
            if ".context-router" in p.parts:
                continue
            yield p


def reconcile_repo(
    store: WorkspaceStore,
    *,
    repo_id: str,
    repo_root: Path,
    sibling_repos: list[tuple[str, Path]],
) -> int:
    """Re-derive cross-repo edges sourced from repo_id; return count written."""
    from contracts_extractor import file_references_endpoint

    sibling_endpoints = _sibling_endpoints(sibling_repos)
    edges: list[CrossRepoEdge] = []
    for source in _scan_source_files(repo_root):
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(source.relative_to(repo_root))
        for dst_repo_id, _method, openapi_path, dst_file in sibling_endpoints:
            if file_references_endpoint(text, openapi_path):
                edges.append(CrossRepoEdge(
                    src_repo_id=repo_id,
                    src_symbol_id=None,
                    src_file=rel,
                    dst_repo_id=dst_repo_id,
                    dst_symbol_id=None,
                    dst_file=dst_file,
                    edge_kind="consumes_openapi",
                    confidence=0.9,
                ))
    return store.replace_edges_for_src(repo_id, edges)
