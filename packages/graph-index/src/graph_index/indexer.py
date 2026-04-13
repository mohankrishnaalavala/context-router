"""Indexer: orchestrates file scanning, analysis, and persistence.

The Indexer is the main entry point for both full and incremental indexing.
It delegates file discovery to FileScanner, analysis to LanguageAnalyzer
plugins, and persistence to SymbolWriter.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from contracts.config import ContextRouterConfig
from contracts.interfaces import LanguageAnalyzer
from core.plugin_loader import PluginLoader
from graph_index.scanner import FileScanner
from graph_index.writer import SymbolWriter
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


@dataclass
class IndexResult:
    """Summary of a completed indexing run."""

    files_scanned: int = 0
    symbols_written: int = 0
    edges_written: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class Indexer:
    """Orchestrates full and incremental repository indexing.

    Usage:
        with Database(db_path) as db:
            loader = PluginLoader()
            loader.discover()
            indexer = Indexer(db, loader, config, "my-repo")
            result = indexer.run(Path("/path/to/repo"))
    """

    def __init__(
        self,
        db: Database,
        plugin_loader: PluginLoader,
        config: ContextRouterConfig,
        repo_name: str,
    ) -> None:
        """Initialise the indexer.

        Args:
            db: An initialised Database (must have initialize() called).
            plugin_loader: A discovered PluginLoader instance.
            config: Project configuration (for ignore patterns, token budget).
            repo_name: Logical repository name stored with every symbol row.
        """
        self._db = db
        self._plugin_loader = plugin_loader
        self._config = config
        self._repo_name = repo_name
        self._sym_repo = SymbolRepository(db.connection)
        self._edge_repo = EdgeRepository(db.connection)
        self._writer = SymbolWriter(self._sym_repo, self._edge_repo)

    def run(self, root: Path) -> IndexResult:
        """Full index: scan all files under root and write to DB.

        Args:
            root: Repository root directory.

        Returns:
            IndexResult with counts and any per-file errors.
        """
        start = time.monotonic()
        result = IndexResult()

        scanner = FileScanner(root, self._config.ignore_patterns, self._plugin_loader)

        for file_path, ext in scanner.scan():
            result.files_scanned += 1
            try:
                analyzer: LanguageAnalyzer | None = self._plugin_loader.get_analyzer(ext)
                if analyzer is None:
                    continue
                analysis = analyzer.analyze(file_path)
                syms, edges = self._writer.write_file_results(
                    self._repo_name, analysis, file_path
                )
                result.symbols_written += syms
                result.edges_written += edges
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{file_path}: {exc}")

        result.duration_seconds = time.monotonic() - start
        # Post-indexing passes: TESTED_BY links + community detection
        try:
            tested_by, communities = self._writer.finalize(self._repo_name)
            result.edges_written += tested_by
        except Exception:  # noqa: BLE001
            pass
        return result

    def run_incremental(self, changed_files: list[Path]) -> IndexResult:
        """Incremental index: re-index only the specified files.

        Args:
            changed_files: List of file paths that changed (absolute or
                relative to cwd). Deleted files are automatically skipped.

        Returns:
            IndexResult with counts and any per-file errors.
        """
        start = time.monotonic()
        result = IndexResult()

        for file_path in changed_files:
            if not file_path.is_file():
                # Deleted — clean up existing records
                self._sym_repo.delete_by_file(self._repo_name, str(file_path))
                self._edge_repo.delete_by_file(self._repo_name, str(file_path))
                continue

            ext = file_path.suffix.lstrip(".")
            analyzer = self._plugin_loader.get_analyzer(ext)
            if analyzer is None:
                continue

            result.files_scanned += 1
            try:
                analysis = analyzer.analyze(file_path)
                syms, edges = self._writer.write_file_results(
                    self._repo_name, analysis, file_path
                )
                result.symbols_written += syms
                result.edges_written += edges
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{file_path}: {exc}")

        result.duration_seconds = time.monotonic() - start
        return result

    def index_file(self, path: Path) -> None:
        """Re-index a single file (used by the file watcher).

        Silently does nothing if the file has no registered analyzer.

        Args:
            path: Absolute path to the changed file.
        """
        ext = path.suffix.lstrip(".")
        analyzer = self._plugin_loader.get_analyzer(ext)
        if analyzer is None:
            return

        try:
            analysis = analyzer.analyze(path)
            self._writer.write_file_results(self._repo_name, analysis, path)
        except Exception:  # noqa: BLE001
            pass  # Watcher must not crash on a single bad file
