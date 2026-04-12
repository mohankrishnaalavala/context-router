"""Orchestrator: coordinates context pack generation across plugins and rankers.

Phase 2 stub — not yet implemented. This module defines the stable public
interface that CLI and MCP server will call. The actual ranking and pack
assembly logic will be added in Phase 2.
"""

from __future__ import annotations

from contracts.models import ContextPack


class Orchestrator:
    """Central coordinator for context pack generation.

    Phase 2 will wire this to the graph-index, ranking, memory, and
    runtime packages. For now all methods raise NotImplementedError.
    """

    def build_pack(self, mode: str, query: str) -> ContextPack:
        """Build and return a ranked ContextPack for the given mode and query.

        Args:
            mode: One of "review", "debug", "implement", "handover".
            query: Free-text description of the task.

        Returns:
            A ContextPack with ranked items.

        Raises:
            NotImplementedError: Always — Phase 2 not yet implemented.
        """
        raise NotImplementedError("Orchestrator.build_pack is implemented in Phase 2")
