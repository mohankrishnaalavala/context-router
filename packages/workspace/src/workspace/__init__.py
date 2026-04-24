"""context-router-workspace: multi-repo workspace registry and cross-repo link detection."""

from __future__ import annotations

from workspace.link_detector import detect_contract_links, detect_links
from workspace.loader import WorkspaceLoader
from workspace.registry import RepoRegistry
from workspace.store import CrossRepoEdge, RepoRecord, WorkspaceStore, open_workspace_db

__all__ = [
    "WorkspaceLoader",
    "RepoRegistry",
    "detect_links",
    "detect_contract_links",
    "CrossRepoEdge",
    "RepoRecord",
    "WorkspaceStore",
    "open_workspace_db",
]
