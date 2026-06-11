"""Indexer: orchestrates file scanning, analysis, and persistence.

The Indexer is the main entry point for both full and incremental indexing.
It delegates file discovery to FileScanner, analysis to LanguageAnalyzer
plugins, and persistence to SymbolWriter.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from contracts.config import ContextRouterConfig
from contracts.interfaces import LanguageAnalyzer
from core.plugin_loader import PluginLoader
from storage_sqlite.database import Database
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

from graph_index.scanner import FileScanner
from graph_index.writer import SymbolWriter

# Files per DELETE chunk when pruning. The edges DELETE binds each chunk
# twice (from_symbol_id + to_symbol_id subqueries), so params per statement
# is 2*chunk + 3. At 400 that is 803 — safely under the 999 bound-variable
# limit of legacy SQLite builds (SQLITE_MAX_VARIABLE_NUMBER pre-3.32).
_PRUNE_CHUNK_SIZE = 400


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

        eligible: set[str] = set()
        for file_path, ext in scanner.scan():
            eligible.add(str(file_path))
            result.files_scanned += 1
            try:
                analyzer: LanguageAnalyzer | None = self._plugin_loader.get_analyzer(ext)
                if analyzer is None:
                    continue
                analysis = analyzer.analyze(file_path)
                syms, edges = self._writer.write_file_results(self._repo_name, analysis, file_path)
                result.symbols_written += syms
                result.edges_written += edges
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"{file_path}: {exc}")

        result.duration_seconds = time.monotonic() - start
        # Prune symbols (and their edges) from files that no longer pass the
        # scanner filter — heals DBs polluted before the v4.5 ignore-pattern
        # fix. Must run BEFORE finalize so TESTED_BY linking and community
        # detection operate on the cleaned graph, not on thousands of junk
        # symbols about to be deleted. Full runs only: run_incremental sees
        # just the changed files, so pruning there would delete every other
        # symbol in the repo.
        self._prune_stale_files(eligible)
        # Post-indexing passes: TESTED_BY links + community detection
        try:
            self._writer.finalize(self._repo_name)
        except Exception:  # noqa: BLE001
            pass
        # v4.6 A3 (DoD v4.6-edge-count-consistency): the reported edge
        # count is the post-dedup stored count — exactly what
        # `SELECT count(*) FROM edges WHERE repo = ?` returns after the
        # run. Accumulated per-file counts drift from storage (cross-file
        # re-resolution on re-runs, finalize's tested_by links, pruning),
        # which is how pydantic reported 24,718 / 27,915 while storing
        # 24,253. Reading the total back from the DB makes reported ==
        # stored by construction, identical on an immediate re-run.
        result.edges_written = self._edge_repo.count(self._repo_name)
        return result

    def _prune_stale_files(self, eligible: set[str]) -> None:
        """Delete symbols/edges whose file_path is no longer scanner-eligible.

        Args:
            eligible: Absolute file paths the scanner yielded during this
                full run. Any symbol row for this repo whose file_path is
                not in this set is stale (ignored or deleted) and removed.
        """
        conn = self._db.connection
        # kind='external' rows are writer-materialized stubs for out-of-repo
        # inheritance targets (file_path '<external>'); they never correspond
        # to a scanned file and must survive the prune or every full run
        # would silently drop all implements/extends-to-framework edges.
        rows = conn.execute(
            "SELECT DISTINCT file_path FROM symbols"
            " WHERE repo = ? AND kind != 'external'",
            (self._repo_name,),
        ).fetchall()
        db_files = {row[0] for row in rows}
        if not eligible and db_files:
            # Zero eligible files but a populated index almost always means a
            # broken environment (e.g. no analyzer installed for this repo's
            # language), not a repo that genuinely lost every source file.
            # Pruning here would wipe the whole index — refuse and warn.
            print(
                "WARN: skipping prune — no eligible files found "
                "(no analyzers for this repo?); index left untouched.",
                file=sys.stderr,
            )
            return
        stale = sorted(db_files - eligible)
        if not stale:
            return

        for i in range(0, len(stale), _PRUNE_CHUNK_SIZE):
            chunk = stale[i : i + _PRUNE_CHUNK_SIZE]
            placeholders = ",".join("?" * len(chunk))
            conn.execute(
                "DELETE FROM edges WHERE repo = ? AND ("
                "from_symbol_id IN (SELECT id FROM symbols WHERE repo = ? "
                f"AND file_path IN ({placeholders})) "
                "OR to_symbol_id IN (SELECT id FROM symbols WHERE repo = ? "
                f"AND file_path IN ({placeholders})))",
                (self._repo_name, self._repo_name, *chunk, self._repo_name, *chunk),
            )
            conn.execute(
                f"DELETE FROM symbols WHERE repo = ? AND file_path IN ({placeholders})",
                (self._repo_name, *chunk),
            )
        conn.commit()

        # Keep the FTS index consistent with the pruned base table. Older
        # DBs without the symbols_fts migration raise OperationalError.
        try:
            conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES ('rebuild')")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        print(
            f"Pruned {len(stale)} symbol file(s) no longer eligible (ignored or deleted).",
            file=sys.stderr,
        )

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
                syms, edges = self._writer.write_file_results(self._repo_name, analysis, file_path)
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
