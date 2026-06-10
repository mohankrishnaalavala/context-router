"""File scanner for context-router graph indexing.

Walks a repository tree and yields files that have a registered language
analyzer, while respecting ignore patterns from config and .gitignore.
"""

from __future__ import annotations

import fnmatch
import os
import sys
from pathlib import Path
from typing import Iterator

import pathspec

from core.plugin_loader import PluginLoader


class FileScanner:
    """Walks a repository directory and yields indexable source files.

    Only yields files whose extension has a registered LanguageAnalyzer
    in the plugin registry. Skips files matching any ignore pattern.
    Respects .gitignore patterns found at the repository root, and prunes
    ignored directories from the walk to avoid descending into large trees
    (e.g. virtual environments, node_modules).
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
        self._gitignore = self._load_gitignore()

    def _load_gitignore(self) -> pathspec.PathSpec | None:
        """Load and parse the root .gitignore file, if present.

        Returns:
            A compiled PathSpec, or None if no .gitignore exists or if it
            cannot be read (in which case a warning is emitted to stderr).
        """
        gi = self._root / ".gitignore"
        if not gi.exists():
            return None
        try:
            lines = gi.read_text(encoding="utf-8", errors="replace").splitlines()
            return pathspec.PathSpec.from_lines("gitignore", lines)
        except OSError as exc:
            print(
                f"WARN: could not read .gitignore ({exc}); "
                "falling back to ignore_patterns only",
                file=sys.stderr,
            )
            return None

    def scan(self) -> Iterator[tuple[Path, str]]:
        """Yield (file_path, extension) for every indexable file under root.

        Uses a directory-pruned os.walk so that ignored directories (e.g.
        virtual environments) are never descended into, avoiding the overhead
        of walking tens of thousands of irrelevant files.

        Yields:
            Tuples of (absolute Path, extension without leading dot).
        """
        for dirpath, dirnames, filenames in os.walk(self._root):
            base = Path(dirpath)
            # Prune ignored directories in-place to prevent os.walk from
            # descending into them.
            dirnames[:] = sorted(
                d for d in dirnames if not self._is_ignored(base / d, is_dir=True)
            )
            for fname in sorted(filenames):
                path = base / fname
                if self._is_ignored(path):
                    continue
                ext = path.suffix.lstrip(".")
                if not ext:
                    continue
                # Only yield files with a registered analyzer
                if self._plugin_loader.get_analyzer(ext) is not None:
                    yield path, ext

    def _is_ignored(self, path: Path, is_dir: bool = False) -> bool:
        """Return True if path matches any ignore pattern or .gitignore rule.

        Checks each path component and the full relative path against the
        configured ignore patterns using fnmatch, then also checks any loaded
        .gitignore PathSpec.

        Args:
            path: Absolute path to test.
            is_dir: If True, appends a trailing '/' to the relative path when
                checking .gitignore rules, so directory-only patterns match.

        Returns:
            True if the path should be skipped.
        """
        try:
            rel = path.relative_to(self._root)
        except ValueError:
            return False

        for pattern in self._ignore_patterns:
            # Match against each path component
            for part in rel.parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
            # Match against the full relative path string
            if fnmatch.fnmatch(str(rel), pattern):
                return True

        if self._gitignore is not None:
            rel_str = str(rel) + ("/" if is_dir else "")
            if self._gitignore.match_file(rel_str):
                return True

        return False
