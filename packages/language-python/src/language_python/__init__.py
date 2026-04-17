"""context-router-language-python: Python language analyzer plugin.

Uses tree-sitter to extract functions, classes, methods, imports, and
inheritance / test-linkage edges from Python source files.  Registered
as the ``py`` analyzer via entry points.

v3 phase3/edge-kinds-extended: emits ``extends`` (class → each base) and
``tested_by`` (source function → test function via the ``test_foo`` →
``foo`` naming convention) edges to match the CRG edge-type vocabulary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from contracts.interfaces import DependencyEdge, Symbol

_LANGUAGE = Language(tspython.language())
_PARSER = Parser(_LANGUAGE)


def _is_test_file(file: Path) -> bool:
    """Return True if *file* looks like a Python test file by naming convention.

    Matches ``test_*.py``, ``*_test.py``, and anything under a ``tests``
    directory (the latter is a soft signal — only used for SUT inference,
    not for emitting spurious edges).
    """
    name = file.name
    if name.startswith("test_") and name.endswith(".py"):
        return True
    if name.endswith("_test.py"):
        return True
    # Under a tests/ directory
    return any(part == "tests" or part == "test" for part in file.parts)


def _text(node: Node) -> str:
    """Return the decoded text of a tree-sitter node."""
    return (node.text or b"").decode("utf-8", errors="replace")


def _first_child_of_type(node: Node, *types: str) -> Node | None:
    """Return the first direct child whose type is in types, or None."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _extract_docstring(body_node: Node) -> str:
    """Extract the docstring from a function/class body block, if present."""
    if not body_node.children:
        return ""
    first = body_node.children[0]
    # In tree-sitter the first statement may be an expression_statement
    # wrapping a string
    if first.type == "expression_statement" and first.children:
        inner = first.children[0]
        if inner.type == "string":
            raw = _text(inner)
            return raw.strip().strip('"""').strip("'''").strip('"').strip("'")
    return ""


_BUILTIN_NAMES: frozenset[str] = frozenset({
    "print", "len", "str", "int", "float", "bool", "list", "dict", "set",
    "tuple", "range", "type", "isinstance", "hasattr", "getattr", "setattr",
    "super", "property", "staticmethod", "classmethod", "enumerate", "zip",
    "map", "filter", "sorted", "reversed", "min", "max", "sum", "any", "all",
    "next", "iter", "open", "vars", "repr", "id", "abs", "round", "format",
    "input", "exit", "quit", "breakpoint", "dir", "help",
})


def _extract_python_base_names(arglist: Node) -> list[str]:
    """Return the base-class identifier names from a Python ``argument_list``.

    Skips keyword arguments (``metaclass=Meta``) so they do NOT show up as
    ``extends`` edges.  Dotted paths like ``some.module.Base`` contribute
    only the leaf identifier (``Base``) so the writer can resolve it.
    """
    names: list[str] = []
    for child in arglist.children:
        if child.type == "identifier":
            names.append(_text(child))
        elif child.type == "attribute":
            # leaf of dotted attribute access
            last_ident = None
            for sub in child.children:
                if sub.type == "identifier":
                    last_ident = sub
            if last_ident is not None:
                names.append(_text(last_ident))
        # keyword_argument (metaclass=Meta) intentionally ignored
    return names


def _walk(
    node: Node,
    results: list[Symbol | DependencyEdge],
    file: Path,
    current_func: str | None = None,
    is_test_file: bool = False,
    non_test_func_names: set[str] | None = None,
    has_emitted_test_edge: list[bool] | None = None,
) -> None:
    """Recursively walk the AST and collect symbols and edges.

    ``is_test_file``/``non_test_func_names`` — when parsing a single file we
    only know the current file's function names, so cross-file Python
    ``tested_by`` linking is completed by the post-indexing
    ``link_tests`` pass.  In-file linking still happens here so small
    self-contained test modules get coverage.
    """
    if node.type == "function_definition":
        name_node = _first_child_of_type(node, "identifier")
        block_node = _first_child_of_type(node, "block")
        name = _text(name_node) if name_node else "<unknown>"
        docstring = _extract_docstring(block_node) if block_node else ""
        # First line = signature
        signature = _text(node).split("\n")[0]
        results.append(
            Symbol(
                name=name,
                kind="function",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="python",
                signature=signature,
                docstring=docstring,
            )
        )
        # v3 phase3/edge-kinds-extended: in-file ``tested_by`` for Python.
        # Handles the tiny fixture pattern where a test function
        # ``test_foo`` and its SUT ``foo`` both live in the same file.
        # Cross-file linking happens via the post-indexing ``link_tests``
        # pass (see graph-index/test_linker.py).
        if (
            is_test_file
            and name.startswith("test_")
            and len(name) > 5
            and non_test_func_names is not None
        ):
            sut = name[5:]
            if sut in non_test_func_names:
                results.append(
                    DependencyEdge(
                        from_symbol=sut,
                        to_symbol=name,
                        edge_type="tested_by",
                    )
                )
                if has_emitted_test_edge is not None:
                    has_emitted_test_edge[0] = True
        # Recurse into body with this function as the enclosing scope
        if block_node:
            _walk(
                block_node,
                results,
                file,
                current_func=name,
                is_test_file=is_test_file,
                non_test_func_names=non_test_func_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return  # Don't double-process function children

    if node.type == "class_definition":
        name_node = _first_child_of_type(node, "identifier")
        block_node = _first_child_of_type(node, "block")
        name = _text(name_node) if name_node else "<unknown>"
        docstring = _extract_docstring(block_node) if block_node else ""
        signature = _text(node).split("\n")[0]
        results.append(
            Symbol(
                name=name,
                kind="class",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="python",
                signature=signature,
                docstring=docstring,
            )
        )
        # v3 phase3/edge-kinds-extended: emit ``extends`` for each base class.
        arglist = _first_child_of_type(node, "argument_list")
        if arglist is not None:
            for base in _extract_python_base_names(arglist):
                results.append(
                    DependencyEdge(
                        from_symbol=name,
                        to_symbol=base,
                        edge_type="extends",
                    )
                )
        if block_node:
            _walk(
                block_node,
                results,
                file,
                current_func=current_func,
                is_test_file=is_test_file,
                non_test_func_names=non_test_func_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return

    if node.type == "call" and current_func is not None:
        # Emit a CALLS edge from the enclosing function to the called symbol.
        func_node = node.children[0] if node.children else None
        called = ""
        if func_node is not None:
            if func_node.type == "identifier":
                called = _text(func_node)
            elif func_node.type == "attribute":
                attr_child = _first_child_of_type(func_node, "identifier")
                called = _text(attr_child) if attr_child else ""
        if called and called not in _BUILTIN_NAMES:
            results.append(
                DependencyEdge(
                    from_symbol=current_func,
                    to_symbol=called,
                    edge_type="calls",
                )
            )
        # Recurse for nested calls
        for child in node.children:
            _walk(
                child,
                results,
                file,
                current_func,
                is_test_file=is_test_file,
                non_test_func_names=non_test_func_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return

    if node.type == "import_statement":
        # import os, import pathlib — emit edges to top-level module name
        for child in node.children:
            if child.type in ("dotted_name", "aliased_import"):
                module = _text(child).split(" as ")[0].strip()
                # Use only the top-level package name as the target symbol name
                top_level = module.split(".")[0]
                results.append(
                    DependencyEdge(
                        from_symbol=str(file),
                        to_symbol=top_level,
                        edge_type="imports",
                    )
                )
        return

    if node.type == "import_from_statement":
        # from contracts.interfaces import DependencyEdge, Symbol
        # Tree-sitter structure:
        #   [from] [dotted_name:module] [import] [dotted_name:A] [,] [dotted_name:B] ...
        # OR wrapped in import_list for parenthesised imports.
        # Emit one edge per imported name so the writer can resolve cross-file refs.
        imported_names: list[str] = []
        past_import_keyword = False
        for child in node.children:
            if child.type == "import":
                past_import_keyword = True
                continue
            if not past_import_keyword:
                continue
            if child.type == "dotted_name":
                # Use only the leaf identifier (e.g. "DependencyEdge" not "contracts.interfaces")
                leaf = _text(child).split(".")[-1]
                imported_names.append(leaf)
            elif child.type == "aliased_import":
                name_child = _first_child_of_type(child, "dotted_name", "identifier")
                if name_child:
                    imported_names.append(_text(name_child).split(".")[-1])
            elif child.type == "import_list":
                for ic in child.children:
                    if ic.type == "dotted_name":
                        imported_names.append(_text(ic).split(".")[-1])
                    elif ic.type == "aliased_import":
                        nc = _first_child_of_type(ic, "dotted_name", "identifier")
                        if nc:
                            imported_names.append(_text(nc).split(".")[-1])
            # wildcard_import (*) — skip

        for name in imported_names:
            results.append(
                DependencyEdge(
                    from_symbol=str(file),
                    to_symbol=name,
                    edge_type="imports",
                )
            )
        return

    # Recurse for all other node types
    for child in node.children:
        _walk(
            child,
            results,
            file,
            current_func,
            is_test_file=is_test_file,
            non_test_func_names=non_test_func_names,
            has_emitted_test_edge=has_emitted_test_edge,
        )


class PythonAnalyzer:
    """Language analyzer for Python source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'py'. Extracts functions, classes, imports, and edges.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a Python source file and return symbols and edges.

        Args:
            path: Absolute path to the .py file.

        Returns:
            List of Symbol and DependencyEdge objects.
        """
        try:
            source = path.read_bytes()
        except OSError:
            return []

        tree = _PARSER.parse(source)
        results: list[Symbol | DependencyEdge] = []

        # v3 phase3/edge-kinds-extended: collect non-test function names in
        # the first pass so in-file ``tested_by`` edges only fire when the
        # SUT is actually defined in the same module.  Cross-file Python
        # ``tested_by`` linking runs in the post-indexing ``link_tests`` pass.
        is_test = _is_test_file(path)
        non_test_func_names: set[str] = set()

        def _collect_func_names(n: Node) -> None:
            if n.type == "function_definition":
                name_node = _first_child_of_type(n, "identifier")
                if name_node:
                    fname = _text(name_node)
                    if not fname.startswith("test_"):
                        non_test_func_names.add(fname)
            for c in n.children:
                _collect_func_names(c)

        if is_test:
            _collect_func_names(tree.root_node)

        has_emitted_test_edge: list[bool] = [False]
        _walk(
            tree.root_node,
            results,
            path,
            is_test_file=is_test,
            non_test_func_names=non_test_func_names,
            has_emitted_test_edge=has_emitted_test_edge,
        )

        # Silent-failure rule: a test file that found no in-file tested_by
        # link is expected when the SUT lives in another module — the
        # post-indexing ``link_tests`` pass covers that case.  We only log
        # a debug note when the file has test_ functions but NONE of them
        # have an in-file SUT AND no companion sources at all (purely
        # informational — the cross-file linker will likely still succeed).
        if is_test and not has_emitted_test_edge[0]:
            has_test_funcs = any(
                isinstance(r, Symbol)
                and r.kind == "function"
                and r.name.startswith("test_")
                for r in results
            )
            if has_test_funcs:
                print(
                    f"[language-python] debug: no in-file SUT for test file {path} "
                    f"(cross-file linking handled by post-indexing link_tests)",
                    file=sys.stderr,
                )

        return results
