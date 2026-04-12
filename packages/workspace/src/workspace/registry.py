"""Repo registry — manages the list of repos in a workspace."""

from __future__ import annotations

from pathlib import Path

from contracts.models import RepoDescriptor, WorkspaceDescriptor

from workspace.loader import WorkspaceLoader, _git_state


class RepoRegistry:
    """In-memory registry of repositories in a workspace.

    Provides add/remove/list operations and can refresh live git state.
    All mutations are reflected in the underlying WorkspaceDescriptor but are
    NOT automatically persisted — callers must call
    ``WorkspaceLoader.save(root, registry.to_descriptor())`` explicitly.
    """

    def __init__(self, descriptor: WorkspaceDescriptor) -> None:
        """Initialise from an existing WorkspaceDescriptor.

        Args:
            descriptor: The workspace to manage.
        """
        self._name = descriptor.name
        self._repos: dict[str, RepoDescriptor] = {r.name: r for r in descriptor.repos}
        self._links: dict[str, list[str]] = dict(descriptor.links)

    # ------------------------------------------------------------------
    # Repo management
    # ------------------------------------------------------------------

    def add(self, name: str, path: Path, language: str = "") -> RepoDescriptor:
        """Add or update a repo entry.

        Enriches with live git state on add.

        Args:
            name: Logical name for the repo.
            path: Filesystem path to the repo root.
            language: Primary language hint (optional).

        Returns:
            The newly created RepoDescriptor.
        """
        branch, sha, dirty = _git_state(path)
        repo = RepoDescriptor(
            name=name,
            path=path,
            language=language,
            branch=branch,
            sha=sha,
            dirty=dirty,
        )
        self._repos[name] = repo
        return repo

    def remove(self, name: str) -> None:
        """Remove a repo from the registry.

        Args:
            name: Repo name to remove.

        Raises:
            KeyError: If the repo name is not in the registry.
        """
        if name not in self._repos:
            raise KeyError(f"Repo {name!r} not found in workspace")
        del self._repos[name]
        # Remove any links involving this repo
        self._links.pop(name, None)
        for v in self._links.values():
            if name in v:
                v.remove(name)

    def get(self, name: str) -> RepoDescriptor | None:
        """Return a single repo by name, or None."""
        return self._repos.get(name)

    def get_all(self) -> list[RepoDescriptor]:
        """Return all repos in the registry."""
        return list(self._repos.values())

    # ------------------------------------------------------------------
    # Link management
    # ------------------------------------------------------------------

    def add_link(self, from_repo: str, to_repo: str) -> None:
        """Add a directional link from *from_repo* to *to_repo*.

        Args:
            from_repo: Source repo name.
            to_repo: Target repo name that from_repo depends on.
        """
        targets = self._links.setdefault(from_repo, [])
        if to_repo not in targets:
            targets.append(to_repo)

    def get_links(self) -> dict[str, list[str]]:
        """Return the current links dict."""
        return dict(self._links)

    # ------------------------------------------------------------------
    # Git state refresh
    # ------------------------------------------------------------------

    def refresh_git_state(self) -> None:
        """Re-query git for branch/sha/dirty on every repo in the registry.

        Silently ignores repos whose paths no longer exist.
        """
        refreshed: dict[str, RepoDescriptor] = {}
        for name, repo in self._repos.items():
            branch, sha, dirty = _git_state(repo.path)
            refreshed[name] = repo.model_copy(
                update={
                    "branch": branch or repo.branch,
                    "sha": sha or repo.sha,
                    "dirty": dirty,
                }
            )
        self._repos = refreshed

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_descriptor(self) -> WorkspaceDescriptor:
        """Convert back to a WorkspaceDescriptor for persistence."""
        return WorkspaceDescriptor(
            name=self._name,
            repos=list(self._repos.values()),
            links=self._links,
        )
