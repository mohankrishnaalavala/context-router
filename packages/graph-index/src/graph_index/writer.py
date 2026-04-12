"""Symbol and edge writer for context-router graph indexing.

Translates the raw list[Symbol | DependencyEdge] returned by language
analyzers into persisted SQLite rows via the repository pattern.
"""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol
from storage_sqlite.repositories import EdgeRepository, SymbolRepository


class SymbolWriter:
    """Writes Symbol and DependencyEdge objects to the SQLite graph store.

    Two-pass strategy:
      Pass 1 — insert all Symbol rows, build name → rowid lookup map.
      Pass 2 — resolve each DependencyEdge against the map and insert.
      Edges whose endpoints cannot be resolved are silently skipped (they
      likely reference symbols in other files; cross-file resolution is a
      Phase 2 concern).
    """

    def __init__(
        self,
        sym_repo: SymbolRepository,
        edge_repo: EdgeRepository,
    ) -> None:
        """Initialise the writer.

        Args:
            sym_repo: Repository for symbol rows.
            edge_repo: Repository for edge rows.
        """
        self._sym_repo = sym_repo
        self._edge_repo = edge_repo

    def write_file_results(
        self,
        repo: str,
        results: list[Symbol | DependencyEdge],
        file_path: Path,
    ) -> tuple[int, int]:
        """Persist analysis results for a single source file.

        Deletes any existing symbols/edges for the file before writing so
        this method is safe to call on re-index.

        Args:
            repo: Logical repository name.
            results: Mixed list of Symbol and DependencyEdge objects.
            file_path: Absolute path of the analysed source file.

        Returns:
            (symbols_written, edges_written) counts.
        """
        file_str = str(file_path)

        # Clear old data for this file (idempotent re-index support)
        self._edge_repo.delete_by_file(repo, file_str)
        self._sym_repo.delete_by_file(repo, file_str)

        symbols = [r for r in results if isinstance(r, Symbol)]
        edges = [r for r in results if isinstance(r, DependencyEdge)]

        # Pass 1: bulk-insert symbols
        if symbols:
            self._sym_repo.add_bulk(symbols, repo)

        # Build a name → id map for edge resolution
        id_map: dict[str, int] = {}
        for sym in symbols:
            sym_id = self._sym_repo.get_id(repo, file_str, sym.name, sym.kind)
            if sym_id is not None:
                id_map[sym.name] = sym_id

        # Pass 2: resolve edges and bulk-insert those we can resolve.
        # Supports cross-file edges where from_symbol is a file path and
        # to_symbol is a symbol name in another file.
        resolved: list[tuple[DependencyEdge, int, int]] = []
        for edge in edges:
            from_id = id_map.get(edge.from_symbol)
            to_id = id_map.get(edge.to_symbol)

            # Cross-file resolution: from_symbol may be an absolute file path
            if from_id is None and ("/" in edge.from_symbol or "\\" in edge.from_symbol):
                from_id = self._sym_repo.get_id_for_file(repo, edge.from_symbol)

            # Cross-file resolution: to_symbol may be a name in another file
            if to_id is None:
                to_id = self._sym_repo.get_id_by_name(repo, edge.to_symbol)

            if from_id is not None and to_id is not None:
                resolved.append((edge, from_id, to_id))

        if resolved:
            self._edge_repo.add_bulk(resolved, repo)

        return len(symbols), len(resolved)
