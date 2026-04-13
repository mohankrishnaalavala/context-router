"""Post-indexing pass: emits TESTED_BY edges from test functions to the symbols they test.

The heuristic is name-based: a test function named ``test_foo`` is assumed to
test a symbol named ``foo`` (or a CamelCase variant).  This is intentionally
simple and produces no false positives for well-named test suites.
"""

from __future__ import annotations

import re

from storage_sqlite.repositories import EdgeRepository, SymbolRepository


def link_tests(
    repo: str,
    sym_repo: SymbolRepository,
    edge_repo: EdgeRepository,
) -> int:
    """Emit TESTED_BY edges by matching test function names to source symbols.

    For each function whose name starts with ``test_``, strip the prefix and
    try to find a non-test symbol with the matching name (or a CamelCase
    variant).  When found, insert a ``tested_by`` edge from the non-test
    symbol to the test function.

    Args:
        repo: Repository identifier.
        sym_repo: SymbolRepository for symbol lookups.
        edge_repo: EdgeRepository for edge insertion.

    Returns:
        Number of TESTED_BY edges written.
    """
    all_symbols = sym_repo.get_all(repo)

    non_test_by_name: dict[str, int] = {}
    test_func_ids: dict[str, int] = {}

    for sym in all_symbols:
        file_str = str(sym.file)
        is_test = "test" in sym.file.name.lower()
        if is_test and sym.kind == "function":
            sid = sym_repo.get_id(repo, file_str, sym.name, sym.kind)
            if sid:
                test_func_ids[sym.name] = sid
        elif not is_test:
            sid = sym_repo.get_id(repo, file_str, sym.name, sym.kind)
            if sid:
                # Last-write-wins if multiple files define the same name
                non_test_by_name[sym.name] = sid

    edges: list[tuple[int, int]] = []  # (source_symbol_id, test_func_id)

    for test_name, test_id in test_func_ids.items():
        if not test_name.startswith("test_"):
            continue
        stripped = re.sub(r"^test_", "", test_name)
        if stripped in non_test_by_name:
            edges.append((non_test_by_name[stripped], test_id))
        # Also try CamelCase variant
        camel = "".join(w.capitalize() for w in stripped.split("_"))
        if camel in non_test_by_name:
            edges.append((non_test_by_name[camel], test_id))

    for source_id, test_id in edges:
        edge_repo.add_raw(repo, source_id, test_id, "tested_by")

    return len(edges)
