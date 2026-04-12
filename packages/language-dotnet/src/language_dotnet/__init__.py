"""context-router-language-dotnet: C#/.NET language analyzer plugin.

Phase 1 stub — analyze() returns an empty list until Tree-sitter
integration is implemented in Phase 1.
"""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol


class DotnetAnalyzer:
    """Language analyzer for C# source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'cs'. Phase 1 will implement namespaces, classes,
    ASP.NET controllers, and xUnit/NUnit/MSTest mapping.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a C# source file and return symbols and edges.

        Args:
            path: Absolute path to the .cs file.

        Returns:
            Empty list (Phase 1 stub).
        """
        return []
