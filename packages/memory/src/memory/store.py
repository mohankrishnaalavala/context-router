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

    def list_by_freshness(self, half_life_days: int = 30) -> list[Observation]:
        """Return all observations sorted by effective_confidence (fresh first).

        Args:
            half_life_days: Days until an observation's base confidence halves.

        Returns:
            All observations, highest effective confidence first.
        """
        from memory.freshness import effective_confidence
        all_obs = self._get_all()
        return sorted(
            all_obs,
            key=lambda o: effective_confidence(o, half_life_days),
            reverse=True,
        )

    def record_access(self, rowid: int) -> None:
        """Increment access_count and update last_accessed_at for an observation.

        Args:
            rowid: SQLite rowid of the observation.
        """
        self._repo.record_access(rowid)

    def find_by_task_hash(self, task_hash: str) -> "Observation | None":
        """Return the first observation with the given task_hash, or None.

        Args:
            task_hash: Short SHA256 hash from the capture guardrail.

        Returns:
            Matching Observation or None.
        """
        return self._repo.find_by_task_hash(task_hash)

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
        return self._repo.get_all()


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
        return [self._repo._row_to_decision(r) for r in rows]  # noqa: SLF001

    def mark_superseded(self, old_id: str, new_id: str) -> None:
        """Mark an old decision as superseded by a newer one.

        Args:
            old_id: UUID of the decision being replaced.
            new_id: UUID of the new decision that supersedes it.
        """
        self._repo.mark_superseded(old_id, new_id)

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
