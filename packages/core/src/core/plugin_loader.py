"""Plugin loader for context-router language analyzers.

Language analyzer plugins register themselves via Python entry points under
the group 'context_router.language_analyzers'. The key must be the file
extension WITHOUT the leading dot (e.g. "py", "java", "cs", "yaml").

Example pyproject.toml entry (in a language plugin package):

    [project.entry-points."context_router.language_analyzers"]
    py = "language_python:PythonAnalyzer"
"""

from __future__ import annotations

from importlib.metadata import entry_points

from contracts.interfaces import LanguageAnalyzer


class PluginLoader:
    """Discovers and registers LanguageAnalyzer plugins via entry points."""

    def __init__(self) -> None:
        """Initialize an empty plugin registry."""
        self._registry: dict[str, LanguageAnalyzer] = {}

    def discover(self) -> None:
        """Load and register all installed language analyzer plugins.

        Iterates over the 'context_router.language_analyzers' entry-points
        group, instantiates each, and registers those that satisfy the
        LanguageAnalyzer protocol. Invalid plugins are silently skipped.
        """
        eps = entry_points(group="context_router.language_analyzers")
        for ep in eps:
            try:
                cls = ep.load()
                instance = cls()
                if isinstance(instance, LanguageAnalyzer):
                    self._registry[ep.name] = instance
            except Exception:
                # Skip plugins that fail to load; don't crash the runner
                pass

    def get_analyzer(self, extension: str) -> LanguageAnalyzer | None:
        """Return the analyzer registered for the given file extension.

        Args:
            extension: File extension WITHOUT leading dot (e.g. "py", "java").

        Returns:
            The registered LanguageAnalyzer, or None if not found.
        """
        return self._registry.get(extension)

    def registered_languages(self) -> list[str]:
        """Return a sorted list of registered extension keys.

        Returns:
            Sorted list of extension strings (e.g. ["cs", "java", "py", "yaml"]).
        """
        return sorted(self._registry.keys())
