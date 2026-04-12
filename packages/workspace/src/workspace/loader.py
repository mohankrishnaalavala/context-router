"""Workspace loader — reads/writes workspace.yaml and enriches with live git state."""

from __future__ import annotations

import subprocess
from pathlib import Path

from contracts.config import load_workspace_config
from contracts.models import RepoDescriptor, WorkspaceDescriptor

_WORKSPACE_FILE = "workspace.yaml"


def _git_state(path: Path) -> tuple[str, str, bool]:
    """Return (branch, sha, dirty) for a git repo at *path*.

    Returns ("", "", False) if the directory is not a git repo or git is not
    available — callers should treat this as "unknown state, not dirty".
    """
    if not path.is_dir():
        return "", "", False

    def _run(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    branch = _run("rev-parse", "--abbrev-ref", "HEAD")
    sha = _run("rev-parse", "--short", "HEAD")
    status_out = _run("status", "--porcelain")
    dirty = bool(status_out)

    return branch, sha, dirty


class WorkspaceLoader:
    """Loads and saves workspace.yaml, enriching repo entries with live git state."""

    @staticmethod
    def load(root: Path) -> WorkspaceDescriptor | None:
        """Load workspace.yaml from *root*, enriching repos with git state.

        Args:
            root: Directory that should contain workspace.yaml.

        Returns:
            WorkspaceDescriptor with live branch/sha/dirty fields set on each
            repo, or None if workspace.yaml does not exist.
        """
        ws = load_workspace_config(root)
        if ws is None:
            return None

        enriched: list[RepoDescriptor] = []
        for repo in ws.repos:
            branch, sha, dirty = _git_state(repo.path)
            enriched.append(
                repo.model_copy(
                    update={
                        "branch": branch or repo.branch,
                        "sha": sha or repo.sha,
                        "dirty": dirty,
                    }
                )
            )

        return ws.model_copy(update={"repos": enriched})

    @staticmethod
    def save(root: Path, ws: WorkspaceDescriptor) -> None:
        """Serialise *ws* to workspace.yaml at *root*.

        Args:
            root: Directory where workspace.yaml will be written.
            ws: The workspace descriptor to persist.
        """
        import yaml  # type: ignore[import-untyped]

        raw = ws.model_dump(mode="json")
        # Convert Path objects to strings for YAML serialisation
        for repo in raw.get("repos", []):
            repo["path"] = str(repo["path"])

        ws_path = root / _WORKSPACE_FILE
        ws_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))

    @staticmethod
    def init(root: Path, name: str = "default") -> WorkspaceDescriptor:
        """Create a new empty workspace.yaml at *root*.

        Args:
            root: Directory where workspace.yaml will be written.
            name: Workspace name.

        Returns:
            The newly created WorkspaceDescriptor.
        """
        ws = WorkspaceDescriptor(name=name, repos=[], links={})
        WorkspaceLoader.save(root, ws)
        return ws
