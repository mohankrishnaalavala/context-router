"""Plugin loader for context-router language analyzers.

Language analyzer plugins register themselves via Python entry points under
the group 'context_router.language_analyzers'. The key must be the file
extension WITHOUT the leading dot (e.g. "py", "java", "cs", "yaml").

Example pyproject.toml entry (in a language plugin package):

    [project.entry-points."context_router.language_analyzers"]
    py = "language_python:PythonAnalyzer"

Silent-failure policy (CLAUDE.md quality gate):
    When a plugin cannot be loaded or does not satisfy the LanguageAnalyzer
    protocol, this loader emits a human-readable warning to stderr naming
    the analyzer and reason. It does NOT swallow the exception silently —
    that class of bug is what made v3.2.0 fresh installs index zero files.
"""

from __future__ import annotations

import sys
from importlib.metadata import entry_points

from contracts.interfaces import LanguageAnalyzer


class PluginLoader:
    """Discovers and registers LanguageAnalyzer plugins via entry points."""

    def __init__(self) -> None:
        """Initialize an empty plugin registry."""
        self._registry: dict[str, LanguageAnalyzer] = {}
        # Diagnostics collected during discover(); consumed by the
        # `context-router doctor` command so operators can see exactly which
        # analyzers failed and why.
        self._load_errors: list[tuple[str, str]] = []

    def discover(self) -> None:
        """Load and register all installed language analyzer plugins.

        Iterates over the 'context_router.language_analyzers' entry-points
        group, instantiates each, and registers those that satisfy the
        LanguageAnalyzer protocol. Failures are logged to stderr AND
        captured in ``self._load_errors`` so the doctor command can report
        them.

        Zero discovered entry points is itself a warning: a fresh install
        that forgot to ship entry_points.txt in its dist-info will trip
        this branch on every invocation.
        """
        eps = list(entry_points(group="context_router.language_analyzers"))
        if not eps:
            self._load_errors.append(
                (
                    "<no-entry-points>",
                    "no 'context_router.language_analyzers' entry points found. "
                    "Language plugins may not be installed; "
                    "`context-router index` will find zero files. "
                    "Run `context-router doctor` for details.",
                )
            )
            print(
                "WARN: no language-analyzer entry points discovered — "
                "index will produce zero symbols. "
                "See `context-router doctor`.",
                file=sys.stderr,
            )
            return

        for ep in eps:
            # Dedupe by extension key: editable + wheel installs can register
            # the same extension twice. First win — matches prior behavior.
            if ep.name in self._registry:
                continue
            try:
                cls = ep.load()
            except Exception as exc:  # noqa: BLE001
                reason = f"failed to import {ep.value!r}: {exc!s}"
                self._load_errors.append((ep.name, reason))
                print(
                    f"WARN: analyzer {ep.name!r} {reason}",
                    file=sys.stderr,
                )
                continue
            try:
                instance = cls()
            except Exception as exc:  # noqa: BLE001
                reason = f"{cls!r}() raised {type(exc).__name__}: {exc!s}"
                self._load_errors.append((ep.name, reason))
                print(
                    f"WARN: analyzer {ep.name!r} {reason}",
                    file=sys.stderr,
                )
                continue
            if not isinstance(instance, LanguageAnalyzer):
                reason = (
                    f"{cls!r} does not satisfy the LanguageAnalyzer protocol"
                )
                self._load_errors.append((ep.name, reason))
                print(
                    f"WARN: analyzer {ep.name!r} {reason}",
                    file=sys.stderr,
                )
                continue
            self._registry[ep.name] = instance

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

    def load_errors(self) -> list[tuple[str, str]]:
        """Return (entry_point_name, reason) pairs for analyzers that failed.

        Used by `context-router doctor` to surface per-analyzer status. An
        empty list means every entry point found was registered successfully.
        """
        return list(self._load_errors)
