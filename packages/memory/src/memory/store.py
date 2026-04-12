"""ObservationStore and DecisionStore — high-level memory access for context-router.

These classes wrap the lower-level repositories in ``storage-sqlite`` and
provide the business-logic operations needed by the CLI and orchestrator:

- Stale observation detection (observations referencing deleted files)
- Tag-based decision retrieval
- JSON import from session files
"""

from __future__ import annotations

import json
from pathlib import Path

from contracts.models import Decision, Observation
from storage_sqlite.database import Database
from storage_sqlite.repositories import DecisionRepository, ObservationRepository, SymbolRepository


class ObservationStore:
    """High-level wrapper around ObservationRepository.

    Args:
        db: An open and initialised Database instance.
    """

    def __init__(self, db: Database) -> None:
        """Initialise the store with an open database.

        Args:
            db: Open Database (caller owns lifetime).
        """
        self._repo = ObservationRepository(db.connection)
        self._sym_repo = SymbolRepository(db.connection)

    def add(self, obs: Observation) -> int:
        """Persist an observation.

        Args:
            obs: Observation to store.

        Returns:
            Row ID of the inserted row.
        """
        return self._repo.add(obs)

    def add_from_session_json(self, session_json: str) -> list[int]:
        """Import observations from a session JSON string.

        Accepts either a single Observation object or a list.  Unknown keys
        are ignored so that session files from other tools can be imported
        without error.

        Args:
            session_json: JSON string — a dict or a list of dicts.

        Returns:
            List of row IDs for all inserted observations.

        Raises:
            ValueError: If the JSON cannot be parsed or validated.
        """
        try:
            raw = json.loads(session_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raise ValueError("Session JSON must be a dict or list of dicts")

        ids: list[int] = []
        for item in raw:
            obs = Observation.model_validate(item)
            ids.append(self._repo.add(obs))
        return ids

    def search(self, query: str) -> list[Observation]:
        """Full-text search observations.

        Args:
            query: FTS5 query string.

        Returns:
            Matching observations, most recently added first.
        """
        return self._repo.search_fts(query)

    def find_stale(self, repo_name: str = "default") -> list[Observation]:
        """Return observations that reference files no longer in the index.

        An observation is considered stale if ALL paths in ``files_touched``
        are absent from the symbol index (i.e. the files have been deleted or
        renamed since the observation was recorded).

        Observations with an empty ``files_touched`` list are never stale.

        Args:
            repo_name: Logical repository name used for the symbol look-up.

        Returns:
            List of stale Observation objects.
        """
        indexed_files = set(self._sym_repo.get_distinct_files(repo_name))
        all_obs = self._repo.search_fts("*") if False else self._get_all()
        stale: list[Observation] = []
        for obs in all_obs:
            if not obs.files_touched:
                continue
            if all(f not in indexed_files for f in obs.files_touched):
                stale.append(obs)
        return stale

    def _get_all(self) -> list[Observation]:
        """Return all stored observations (used internally)."""
        # Use a broad FTS query that matches everything
        # FTS5: empty query is an error; use a wildcard approach via raw SQL
        rows = self._repo._conn.execute(  # noqa: SLF001
            "SELECT * FROM observations ORDER BY id DESC"
        ).fetchall()
        import json as _json
        from datetime import datetime
        return [
            Observation(
                timestamp=datetime.fromisoformat(r["timestamp"]),
                task_type=r["task_type"] or "",
                summary=r["summary"] or "",
                files_touched=_json.loads(r["files_touched"] or "[]"),
                commands_run=_json.loads(r["commands_run"] or "[]"),
                failures_seen=_json.loads(r["failures_seen"] or "[]"),
                fix_summary=r["fix_summary"] or "",
                commit_sha=r["commit_sha"] or "",
                repo_scope=r["repo_scope"] or "",
            )
            for r in rows
        ]


class DecisionStore:
    """High-level wrapper around DecisionRepository.

    Args:
        db: An open and initialised Database instance.
    """

    def __init__(self, db: Database) -> None:
        """Initialise the store with an open database.

        Args:
            db: Open Database (caller owns lifetime).
        """
        self._repo = DecisionRepository(db.connection)

    def add(self, decision: Decision) -> str:
        """Persist a decision.

        Args:
            decision: Decision to store.

        Returns:
            UUID string of the inserted decision.
        """
        return self._repo.add(decision)

    def search(self, query: str) -> list[Decision]:
        """Full-text search decisions.

        Args:
            query: FTS5 query string.

        Returns:
            Matching decisions, most recently created first.
        """
        return self._repo.search_fts(query)

    def get_all(self) -> list[Decision]:
        """Return all stored decisions, most recently created first."""
        rows = self._repo._conn.execute(  # noqa: SLF001
            "SELECT * FROM decisions ORDER BY created_at DESC"
        ).fetchall()
        import json as _json
        from datetime import datetime
        return [
            Decision(
                id=r["id"],
                title=r["title"],
                status=r["status"],
                context=r["context"] or "",
                decision=r["decision"] or "",
                consequences=r["consequences"] or "",
                tags=_json.loads(r["tags"] or "[]"),
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    def by_tags(self, tags: list[str]) -> list[Decision]:
        """Return decisions that have at least one of the given tags.

        Args:
            tags: List of tag strings to filter by.

        Returns:
            Matching Decision objects.
        """
        all_decisions = self.get_all()
        tag_set = set(t.lower() for t in tags)
        return [d for d in all_decisions if tag_set & {t.lower() for t in d.tags}]
