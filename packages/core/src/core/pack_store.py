"""On-disk registry of generated ContextPacks.

Backs the MCP ``resources`` capability (P3-6) — every pack built through the
Orchestrator is persisted as ``.context-router/packs/<uuid>.json`` with an
index file at ``.context-router/packs/index.json``.  LRU eviction keeps the
most recent 20 packs per project.

The MCP server exposes each pack as a ``context-router://packs/<uuid>``
resource and emits ``notifications/resources/list_changed`` when the set
changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from contracts.models import ContextPack

__all__ = ["PackStore", "PackStoreEntry"]

_MAX_PACKS = 20


class PackStoreEntry(TypedDict):
    """Metadata recorded in the index for one stored pack."""

    uuid: str
    mode: str
    query: str
    created_at: str
    tokens: int


class PackStore:
    """Durable, newest-first registry of ContextPacks with LRU retention.

    Layout::

        <project_root>/.context-router/packs/
            index.json           # list[PackStoreEntry], newest first
            <uuid>.json          # one file per persisted pack
            .gitignore           # ensures packs/ is ignored from git

    The API is intentionally narrow — callers never construct entries by
    hand; they pass a ``ContextPack`` instance and receive back the same
    metadata that will appear in :meth:`list`.
    """

    def __init__(self, project_root: Path) -> None:
        """Initialise the store rooted at *project_root*.

        Args:
            project_root: The project directory that owns the
                ``.context-router/`` folder.  Created on first write if absent.
        """
        self._root = Path(project_root)
        self._dir = self._root / ".context-router" / "packs"
        self._index_path = self._dir / "index.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, pack: ContextPack) -> PackStoreEntry:
        """Persist *pack* and return the registry entry.

        Evicts the oldest pack when the registry would exceed
        :data:`_MAX_PACKS` entries.

        Args:
            pack: The :class:`ContextPack` to store.

        Returns:
            The :class:`PackStoreEntry` written to the index file.
        """
        self._ensure_dir()
        pack_path = self._dir / f"{pack.id}.json"
        pack_path.write_text(pack.model_dump_json(indent=2))

        entry: PackStoreEntry = {
            "uuid": pack.id,
            "mode": pack.mode,
            "query": pack.query,
            "created_at": pack.created_at.isoformat(),
            "tokens": pack.total_est_tokens,
        }

        index = self._read_index()
        # Remove any stale entry for this uuid, prepend the fresh one
        index = [e for e in index if e.get("uuid") != pack.id]
        index.insert(0, entry)

        # LRU eviction — drop oldest beyond _MAX_PACKS
        if len(index) > _MAX_PACKS:
            for evicted in index[_MAX_PACKS:]:
                evicted_uuid = evicted.get("uuid")
                if evicted_uuid:
                    evicted_path = self._dir / f"{evicted_uuid}.json"
                    if evicted_path.exists():
                        evicted_path.unlink()
            index = index[:_MAX_PACKS]

        self._write_index(index)
        return entry

    def list(self) -> list[PackStoreEntry]:
        """Return all registry entries, newest first."""
        return self._read_index()

    def get(self, uuid: str) -> ContextPack | None:
        """Return the :class:`ContextPack` for *uuid*, or ``None`` if absent."""
        pack_path = self._dir / f"{uuid}.json"
        if not pack_path.exists():
            return None
        try:
            return ContextPack.model_validate_json(pack_path.read_text())
        except Exception:  # noqa: BLE001 — corrupt/truncated file should act as absent
            return None

    def delete(self, uuid: str) -> bool:
        """Remove the pack *uuid* from disk and the index.

        Returns:
            ``True`` if the pack existed and was removed; ``False`` otherwise.
        """
        index = self._read_index()
        remaining = [e for e in index if e.get("uuid") != uuid]
        pack_path = self._dir / f"{uuid}.json"
        existed = pack_path.exists() or len(remaining) != len(index)
        if pack_path.exists():
            pack_path.unlink()
        if len(remaining) != len(index):
            self._write_index(remaining)
        return existed

    def read_raw(self, uuid: str) -> str | None:
        """Return the stored pack's raw JSON text for *uuid*, or ``None``.

        Used by the MCP ``resources/read`` handler so the response is
        byte-for-byte identical to the on-disk ``last-pack.json`` form.
        """
        pack_path = self._dir / f"{uuid}.json"
        if not pack_path.exists():
            return None
        return pack_path.read_text()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        """Create the packs directory and the local .gitignore if missing."""
        self._dir.mkdir(parents=True, exist_ok=True)
        gitignore = self._dir.parent / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Auto-generated by context-router\npacks/\n")
        else:
            text = gitignore.read_text()
            if "packs/" not in text.splitlines():
                if text and not text.endswith("\n"):
                    text += "\n"
                text += "packs/\n"
                gitignore.write_text(text)

    def _read_index(self) -> list[PackStoreEntry]:
        if not self._index_path.exists():
            return []
        try:
            raw = json.loads(self._index_path.read_text())
            if isinstance(raw, list):
                return [entry for entry in raw if isinstance(entry, dict)]
        except json.JSONDecodeError:
            return []
        return []

    def _write_index(self, entries: list[PackStoreEntry]) -> None:
        self._ensure_dir()
        self._index_path.write_text(json.dumps(entries, indent=2))
