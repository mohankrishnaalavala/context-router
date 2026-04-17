"""Symbol and edge writer for context-router graph indexing.

Translates the raw list[Symbol | DependencyEdge] returned by language
analyzers into persisted SQLite rows via the repository pattern.
"""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol
from storage_sqlite.repositories import EdgeRepository, SymbolRepository
from graph_index.community import compute_communities
from graph_index.test_linker import link_tests


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
        # Supports cross-file edges where the source or target is a symbol
        # name in another file.  The writer also resolves a file-path
        # source (used for ``imports`` edges whose from_symbol is the file).
        resolved: list[tuple[DependencyEdge, int, int]] = []
        # v3 phase3/edge-kinds-extended: inheritance edges often point at
        # external framework types (``Serializable``, ``JpaRepository``,
        # ``WebMvcConfigurer``) that are not defined in-project.  Rather
        # than dropping the edge and losing the signal, we materialize a
        # lightweight ``external`` symbol stub for the target the first
        # time it is referenced.  This matches code-review-graph's
        # convention of surfacing every referenced type as a node and
        # unlocks downstream ranking (hub-bridge, TESTED_BY coverage).
        _INHERITANCE_KINDS = {"extends", "implements"}
        external_id_cache: dict[str, int] = {}

        def _materialize_external(name: str) -> int | None:
            """Return a symbol id for an external inheritance target.

            Idempotent per (repo, name): creates the stub only on the
            first miss, reuses thereafter.  Kind is ``external`` so it
            cannot collide with analyzer-emitted kinds.
            """
            if not name or name in external_id_cache:
                return external_id_cache.get(name)
            existing = self._sym_repo.get_id_by_name(repo, name)
            if existing is not None:
                external_id_cache[name] = existing
                return existing
            stub = Symbol(
                name=name,
                kind="external",
                file=Path("<external>"),
                line_start=0,
                line_end=0,
                language="external",
                signature=f"external {name}",
            )
            sid = self._sym_repo.add(stub, repo)
            external_id_cache[name] = sid
            return sid

        for edge in edges:
            from_id = id_map.get(edge.from_symbol)
            to_id = id_map.get(edge.to_symbol)

            # Cross-file resolution: from_symbol may be an absolute file path
            if from_id is None and ("/" in edge.from_symbol or "\\" in edge.from_symbol):
                from_id = self._sym_repo.get_id_for_file(repo, edge.from_symbol)

            # Cross-file resolution: from_symbol may be a name defined in
            # another file (used by extends / implements / tested_by where
            # the analyzer cannot know the target symbol's file at parse
            # time — the source class of a ``tested_by`` edge often lives
            # in a different file than the test class).
            if from_id is None:
                from_id = self._sym_repo.get_id_by_name(repo, edge.from_symbol)

            # Cross-file resolution: to_symbol may be a name in another file
            if to_id is None:
                to_id = self._sym_repo.get_id_by_name(repo, edge.to_symbol)

            # External-target fallback for inheritance edges only (NOT for
            # ``calls`` / ``imports`` / ``tested_by`` — those stay strict
            # so spurious edges cannot flood the graph).
            if to_id is None and edge.edge_type in _INHERITANCE_KINDS:
                to_id = _materialize_external(edge.to_symbol)

            if from_id is not None and to_id is not None:
                resolved.append((edge, from_id, to_id))

        if resolved:
            self._edge_repo.add_bulk(resolved, repo)

        return len(symbols), len(resolved)

    def finalize(self, repo: str) -> tuple[int, int]:
        """Run post-indexing passes: TESTED_BY link detection and community detection.

        Call once after all files have been indexed for a repository.

        Args:
            repo: Logical repository name.

        Returns:
            (tested_by_edges, communities) counts.
        """
        tested_by = link_tests(repo, self._sym_repo, self._edge_repo)
        communities = compute_communities(repo, self._sym_repo, self._edge_repo)
        return tested_by, communities
