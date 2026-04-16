"""MCP ``resources/*`` handlers for context-router.

Each stored pack from :class:`core.pack_store.PackStore` is exposed as a
``context-router://packs/<uuid>`` resource.  The MCP server (main.py)
wires these functions into its JSON-RPC dispatch loop so clients can
enumerate and retrieve previously built packs without re-running
``get_context_pack``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.pack_store import PackStore

__all__ = ["list_resources", "read_resource", "URI_PREFIX"]

URI_PREFIX = "context-router://packs/"


def _store(project_root: str | None) -> PackStore:
    """Return a :class:`PackStore` rooted at *project_root* or the cwd."""
    root = Path(project_root) if project_root else Path.cwd()
    return PackStore(root)


def list_resources(project_root: str | None = None) -> dict[str, Any]:
    """Return all stored packs as MCP resource descriptors.

    Args:
        project_root: Optional absolute project path; defaults to ``cwd``.

    Returns:
        A dict of the form ``{"resources": [{uri, name, mimeType, description}, ...]}``
        suitable for the ``resources/list`` JSON-RPC response.
    """
    entries = _store(project_root).list()
    resources: list[dict[str, Any]] = []
    for entry in entries:
        uid = entry["uuid"]
        query = entry.get("query") or "(no query)"
        mode = entry.get("mode", "")
        tokens = entry.get("tokens", 0)
        created = entry.get("created_at", "")
        resources.append({
            "uri": f"{URI_PREFIX}{uid}",
            "name": f"{mode} pack — {query[:60]}",
            "mimeType": "application/json",
            "description": (
                f"Context pack (mode={mode}, tokens={tokens}, created_at={created})"
            ),
        })
    return {"resources": resources}


def read_resource(uri: str, project_root: str | None = None) -> dict[str, Any]:
    """Return the stored pack's canonical JSON for the given *uri*.

    The text payload is byte-for-byte identical to the on-disk pack file
    so round-trips through an MCP client preserve every field.

    Args:
        uri: Full ``context-router://packs/<uuid>`` URI.
        project_root: Optional absolute project path; defaults to ``cwd``.

    Returns:
        ``{"contents": [{uri, mimeType, text}]}`` ready for the
        ``resources/read`` JSON-RPC response.

    Raises:
        ValueError: If *uri* does not use the ``context-router://packs/``
            scheme or lacks a UUID segment.
        FileNotFoundError: If the UUID does not match any stored pack.
    """
    if not uri.startswith(URI_PREFIX):
        raise ValueError(
            f"Unsupported resource URI scheme: {uri!r} "
            f"(expected prefix {URI_PREFIX!r})"
        )
    uuid = uri[len(URI_PREFIX):]
    if not uuid:
        raise ValueError(f"Resource URI missing uuid segment: {uri!r}")

    text = _store(project_root).read_raw(uuid)
    if text is None:
        raise FileNotFoundError(f"No stored pack with uuid={uuid!r}")

    return {
        "contents": [
            {"uri": uri, "mimeType": "application/json", "text": text}
        ]
    }
