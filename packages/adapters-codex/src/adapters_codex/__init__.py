"""context-router-adapters-codex: Codex agent adapter.

Phase 6 stub — generate() returns an empty string until subagent
task prompt generation is implemented in Phase 6.
"""

from __future__ import annotations

from contracts.models import ContextPack


class CodexAdapter:
    """Agent adapter that generates Codex-compatible subagent task prompts.

    Phase 6 will implement prompt construction with inlined context items
    suitable for Codex's subagent/task format.
    """

    def generate(self, pack: ContextPack) -> str:
        """Generate a Codex subagent task prompt from a ContextPack.

        Args:
            pack: The ranked context pack to render.

        Returns:
            Empty string (Phase 6 stub).
        """
        return ""
