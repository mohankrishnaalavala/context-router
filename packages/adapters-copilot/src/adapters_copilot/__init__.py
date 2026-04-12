"""context-router-adapters-copilot: GitHub Copilot agent adapter.

Phase 6 stub — generate() returns an empty string until
.github/copilot-instructions.md and agent file generation are
implemented in Phase 6.
"""

from __future__ import annotations

from contracts.models import ContextPack


class CopilotAdapter:
    """Agent adapter that generates GitHub Copilot instructions and agent files.

    Phase 6 will implement generation of:
    - .github/copilot-instructions.md
    - .github/agents/review.agent.md
    - .github/agents/debug.agent.md
    - .github/agents/implement.agent.md
    - .github/agents/handover.agent.md
    """

    def generate(self, pack: ContextPack) -> str:
        """Generate Copilot instructions content from a ContextPack.

        Args:
            pack: The ranked context pack to render.

        Returns:
            Empty string (Phase 6 stub).
        """
        return ""
