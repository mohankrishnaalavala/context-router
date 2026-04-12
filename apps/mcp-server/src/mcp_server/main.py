"""MCP server entrypoint for context-router.

Phase 5 stub — the stdio MCP server and all 8 tools will be implemented
in Phase 5. This entrypoint exists to satisfy the package script entry
point and provide a stable import surface.
"""

from __future__ import annotations

import sys


def main() -> None:
    """Start the context-router MCP server.

    Phase 5 stub: prints a not-implemented message and exits cleanly.
    """
    print(
        "context-router MCP server is not yet implemented (Phase 5).",
        file=sys.stderr,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
