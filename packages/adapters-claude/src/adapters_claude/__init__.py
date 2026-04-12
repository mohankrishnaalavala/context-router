"""context-router-adapters-claude: Claude Code agent adapter.

Phase 6 stub — generate() returns an empty string until prompt
generation is implemented in Phase 6.
"""

from __future__ import annotations

from contracts.models import ContextPack


class ClaudeAdapter:
    """Agent adapter that generates task-specific prompt preambles for Claude Code.

    Phase 6 will implement prompt construction from ContextPack items,
    including task mode framing and item-level rationale formatting.
    """

    def generate(self, pack: ContextPack) -> str:
        """Generate a Claude Code prompt preamble from a ContextPack.

        Args:
            pack: The ranked context pack to render.

        Returns:
            Empty string (Phase 6 stub).
        """
        return ""
