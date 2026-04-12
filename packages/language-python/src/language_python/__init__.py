"""context-router-language-python: Python language analyzer plugin.

Phase 1 stub — analyze() returns an empty list until Tree-sitter
integration is implemented in Phase 1.
"""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol


class PythonAnalyzer:
    """Language analyzer for Python source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'py'. Phase 1 will implement Tree-sitter-based
    extraction of imports, functions, classes, and endpoint definitions.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a Python source file and return symbols and edges.

        Args:
            path: Absolute path to the .py file.

        Returns:
            Empty list (Phase 1 stub).
        """
        return []
