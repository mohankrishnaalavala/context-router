"""context-router-language-yaml: YAML language analyzer plugin.

Phase 1 stub — analyze() returns an empty list until key-path extraction
and Kubernetes/GitHub Actions detection are implemented in Phase 1.
"""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol


class YamlAnalyzer:
    """Language analyzer for YAML files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'yaml'. Phase 1 will implement key-path extraction,
    Kubernetes resource detection, GitHub Actions job/step extraction,
    and Helm chart detection.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a YAML file and return symbols and edges.

        Args:
            path: Absolute path to the .yaml/.yml file.

        Returns:
            Empty list (Phase 1 stub).
        """
        return []
