"""File scanner for context-router graph indexing.

Walks a repository tree and yields files that have a registered language
analyzer, while respecting ignore patterns from config.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Iterator

from core.plugin_loader import PluginLoader


class FileScanner:
    """Walks a repository directory and yields indexable source files.

    Only yields files whose extension has a registered LanguageAnalyzer
    in the plugin registry. Skips files matching any ignore pattern.
    """

    def __init__(
        self,
        root: Path,
        ignore_patterns: list[str],
        plugin_loader: PluginLoader,
    ) -> None:
        """Initialise the scanner.

        Args:
            root: Repository root directory to walk.
            ignore_patterns: List of fnmatch-style patterns to skip
                (e.g. [".git", "__pycache__", "*.pyc"]).
            plugin_loader: A discovered PluginLoader used to check which
                extensions have registered analyzers.
        """
        self._root = root
        self._ignore_patterns = ignore_patterns
        self._plugin_loader = plugin_loader

    def scan(self) -> Iterator[tuple[Path, str]]:
        """Yield (file_path, extension) for every indexable file under root.

        Yields:
            Tuples of (absolute Path, extension without leading dot).
        """
        for path in sorted(self._root.rglob("*")):
            if not path.is_file():
                continue
            if self._is_ignored(path):
                continue
            ext = path.suffix.lstrip(".")
            if not ext:
                continue
            # Only yield files with a registered analyzer
            if self._plugin_loader.get_analyzer(ext) is not None:
                yield path, ext

    def _is_ignored(self, path: Path) -> bool:
        """Return True if path matches any ignore pattern.

        Checks each path component and the full relative path against the
        configured ignore patterns using fnmatch.

        Args:
            path: Absolute path to test.

        Returns:
            True if the path should be skipped.
        """
        try:
            rel = path.relative_to(self._root)
        except ValueError:
            return False

        parts = rel.parts
        for pattern in self._ignore_patterns:
            # Match against each path component
            for part in parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
            # Match against the full relative path string
            if fnmatch.fnmatch(str(rel), pattern):
                return True
        return False
