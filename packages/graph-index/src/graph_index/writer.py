"""Symbol and edge writer for context-router graph indexing.

Translates the raw list[Symbol | DependencyEdge] returned by language
analyzers into persisted SQLite rows via the repository pattern.
"""

from __future__ import annotations

import sys
from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol
from storage_sqlite.repositories import EdgeRepository, SymbolRepository

from graph_index.community import compute_communities
from graph_index.test_linker import link_tests

# v3 phase4/edge-source-resolution-fix: edge kinds whose ``from_symbol``
# MUST anchor on a type declaration (class / record / interface / enum
# / struct) — never on a constructor or method that happens to share
# the class name.  Constructors share the class name by language rule,
# so a naive name-based lookup picked the constructor row whenever it
# appeared first in the table, which corrupted the directionality of
# inheritance queries (``SELECT from_kind FROM edges WHERE edge_type
# IN ('extends','implements')`` reported ``constructor`` rows that
# should have been ``class`` rows).
_CLASS_LIKE_KINDS: tuple[str, ...] = ("class", "record", "interface", "enum", "struct")
_INHERITANCE_SOURCE_KINDS: frozenset[str] = frozenset(
    {"extends", "implements", "tested_by"}
)


def _qualify_symbols(symbols: list[Symbol]) -> None:
    """Assign scope-qualified identities to *symbols* in place (v4.6 A2).

    Analyzers emit flat symbols without parent links, but the enclosing
    scope is recoverable from line containment: a symbol whose line range
    strictly encloses another's is its ancestor. The qualified identity is
    the parent-symbol chain joined with ``.`` (``test_a.Model``), which
    keeps same-named definitions at different sites in one file DISTINCT.

    Fallback (DoD v4.6-symbol-qualification): when the parent chain cannot
    disambiguate — e.g. two module-level redefinitions of the same name —
    the colliding occurrence is suffixed with its definition line
    (``setup@7``). Applied ONLY on collision so stable, human-readable
    chains stay the common case.
    """
    # Outer scopes first: by start line, then widest span on ties.
    ordered = sorted(symbols, key=lambda s: (s.line_start, -(s.line_end or 0)))
    stack: list[Symbol] = []
    assigned: set[str] = set()
    for sym in ordered:
        while stack and not (
            stack[-1].line_start <= sym.line_start
            and (stack[-1].line_end or 0) >= (sym.line_end or 0)
        ):
            stack.pop()
        chain = [parent.name for parent in stack]
        qualified = ".".join([*chain, sym.name])
        if qualified in assigned:
            qualified = f"{qualified}@{sym.line_start}"
        assigned.add(qualified)
        sym.qualified_name = qualified
        stack.append(sym)


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

        # v4.6 A2: compute scope-qualified identities BEFORE insert so
        # same-named symbols at different definition sites in this file
        # persist as distinct identities (DoD v4.6-symbol-qualification).
        _qualify_symbols(symbols)

        # Pass 1: bulk-insert symbols, keeping per-occurrence rowids.
        sym_row_ids: dict[int, int] = {}  # id(Symbol object) -> rowid
        if symbols:
            inserted_ids = self._sym_repo.add_bulk(symbols, repo)
            sym_row_ids = {
                id(sym): rid for sym, rid in zip(symbols, inserted_ids)
            }

        # Build name → id maps for edge resolution.
        # v3 phase4/edge-source-resolution-fix: also build a class-kind
        # overlay so inheritance / tested_by source resolution can
        # disambiguate class vs. constructor rows that share a name.
        # v4.6 A2: these whole-file maps are the FALLBACK for forward
        # references; the per-occurrence positional maps built while
        # walking ``results`` below take precedence so each edge anchors
        # on the definition site that emitted it, not on the first row
        # that happened to share the name.
        id_map: dict[str, int] = {}
        class_id_map: dict[str, int] = {}
        for sym in symbols:
            sym_id = sym_row_ids.get(id(sym))
            if sym_id is not None:
                # First writer wins for id_map so we don't accidentally
                # overwrite a class row with its constructor row (same
                # name, different kinds, same file).
                if sym.name not in id_map:
                    id_map[sym.name] = sym_id
                if sym.kind in _CLASS_LIKE_KINDS:
                    class_id_map[sym.name] = sym_id

        # Pass 2: resolve edges and bulk-insert those we can resolve.
        # Supports cross-file edges where the source or target is a symbol
        # name in another file.  The writer also resolves a file-path
        # source (used for ``imports`` edges whose from_symbol is the file).
        resolved: list[tuple[DependencyEdge, int, int]] = []
        # v4.6 A2 positional maps: while walking ``results`` in analyzer
        # emission order, these always hold the MOST RECENT definition of
        # each name, so an edge emitted right after its defining symbol
        # (the analyzer's contract) anchors on that exact occurrence.
        last_id_by_name: dict[str, int] = {}
        last_class_id_by_name: dict[str, int] = {}
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

        def _resolve_source_symbol_id(edge: DependencyEdge) -> int | None:
            """Resolve the ``from_symbol_id`` for *edge*.

            v3 phase4/edge-source-resolution-fix: ``extends`` /
            ``implements`` / ``tested_by`` edges MUST anchor on a class /
            record / interface / enum / struct row — never on a
            constructor that shares the class name.  The analyzer emits
            these edges keyed by the class NAME (a string), so the
            writer is responsible for picking the correct row when
            multiple symbols share that name.

            Resolution order for inheritance edges:
              1. In-file class-kind overlay (``class_id_map``).
              2. Cross-file class-kind lookup via a kind-filtered SQL
                 query against the repo connection.
              3. Any-kind fallback (existing ``id_map`` / file-path /
                 ``get_id_by_name``) so we don't regress when the
                 preferred row is unavailable (e.g. partial indexing).
              4. Stderr debug note if every lookup fails.  No row is
                 created and the edge is dropped (CLAUDE.md
                 silent-failure rule — every drop is logged).

            For other edge kinds (``calls``, ``imports``), behavior is
            unchanged: fall through to the legacy in-file + cross-file
            resolution chain.
            """
            name = edge.from_symbol
            if edge.edge_type not in _INHERITANCE_SOURCE_KINDS:
                return None  # legacy path handles this case

            # 1. Prefer the class-like row in the current file — the most
            # recently defined occurrence first (v4.6 A2: nested
            # same-named classes are distinct identities, and the edge the
            # analyzer emitted right after a definition belongs to that
            # definition), then the whole-file first-wins map for forward
            # references.
            fid = last_class_id_by_name.get(name)
            if fid is None:
                fid = class_id_map.get(name)
            if fid is not None:
                return fid

            # 2. Kind-filtered cross-file lookup.  We go through the
            # repo's SQLite connection because ``SymbolRepository`` does
            # not expose a kind-filtered by-name query; this single
            # statement keeps the fix scoped to the writer.
            placeholders = ",".join("?" for _ in _CLASS_LIKE_KINDS)
            row = self._sym_repo._conn.execute(  # noqa: SLF001
                f"""
                SELECT id FROM symbols
                WHERE repo = ? AND name = ? AND kind IN ({placeholders})
                LIMIT 1
                """,
                (repo, name, *_CLASS_LIKE_KINDS),
            ).fetchone()
            if row is not None:
                return row["id"]

            # 3. Any-kind fallback so we don't silently drop edges where
            # the class is simply not indexed yet (partial repo /
            # symlinked code) — preserve the previous resolution chain.
            fallback = id_map.get(name)
            if fallback is None and ("/" in name or "\\" in name):
                fallback = self._sym_repo.get_id_for_file(repo, name)
            if fallback is None:
                fallback = self._sym_repo.get_id_by_name(repo, name)
            if fallback is not None:
                # CLAUDE.md silent-failure rule: the edge is kept, but
                # warn that we had to settle for a non-class row so
                # consumers can spot partial indexing.
                print(
                    f"[graph-index] debug: {edge.edge_type} source '{name}' "
                    f"resolved to a non-class row (no class/record/interface/"
                    f"enum/struct match in repo={repo!r}); edge kept on "
                    f"fallback id={fallback}",
                    file=sys.stderr,
                )
                return fallback

            # 4. Nothing matched — log and drop.
            print(
                f"[graph-index] debug: cannot resolve {edge.edge_type} source "
                f"'{name}' in repo={repo!r}; edge dropped",
                file=sys.stderr,
            )
            return None

        # v4.6 A2: walk ``results`` in analyzer emission order so each
        # edge resolves against the definitions seen SO FAR. Analyzers
        # emit a definition's edges immediately after its Symbol, so the
        # "most recent occurrence" is the defining scope — this is what
        # keeps N same-named nested classes anchored to N distinct rows.
        for item in results:
            if isinstance(item, Symbol):
                rid = sym_row_ids.get(id(item))
                if rid is not None:
                    last_id_by_name[item.name] = rid
                    if item.kind in _CLASS_LIKE_KINDS:
                        last_class_id_by_name[item.name] = rid
                continue

            edge = item
            # v3 phase4/edge-source-resolution-fix: for inheritance /
            # tested_by edges the source anchoring is class-kind-strict.
            # The helper handles in-file preference, kind-filtered
            # cross-file lookup, fallback, and stderr logging — so when
            # it returns None we skip the edge entirely.
            if edge.edge_type in _INHERITANCE_SOURCE_KINDS:
                from_id = _resolve_source_symbol_id(edge)
                to_id = last_id_by_name.get(edge.to_symbol)
                if to_id is None:
                    to_id = id_map.get(edge.to_symbol)
                if to_id is None:
                    to_id = self._sym_repo.get_id_by_name(repo, edge.to_symbol)
            else:
                from_id = last_id_by_name.get(edge.from_symbol)
                if from_id is None:
                    from_id = id_map.get(edge.from_symbol)
                to_id = last_id_by_name.get(edge.to_symbol)
                if to_id is None:
                    to_id = id_map.get(edge.to_symbol)

                # Cross-file resolution: from_symbol may be an absolute file path
                if from_id is None and ("/" in edge.from_symbol or "\\" in edge.from_symbol):
                    from_id = self._sym_repo.get_id_for_file(repo, edge.from_symbol)

                # Cross-file resolution: from_symbol may be a name defined in
                # another file.
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

        # v4.6 A1: add_bulk pre-aggregates duplicate occurrences into a
        # single weighted row, so the count it returns (unique rows
        # written) is the honest "edges written" number — len(resolved)
        # would overstate by the collapsed multiplicity.
        edges_written = (
            self._edge_repo.add_bulk(resolved, repo) if resolved else 0
        )

        return len(symbols), edges_written

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
