"""context-router-language-java: Java language analyzer plugin.

Phase 1 stub — analyze() returns an empty list until Tree-sitter
integration is implemented in Phase 1.
"""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol


class JavaAnalyzer:
    """Language analyzer for Java source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'java'. Phase 1 will implement packages, classes,
    Spring annotations, and JUnit test mapping.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a Java source file and return symbols and edges.

        Args:
            path: Absolute path to the .java file.

        Returns:
            Empty list (Phase 1 stub).
        """
        return []
