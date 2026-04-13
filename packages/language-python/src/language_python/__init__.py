"""context-router-language-python: Python language analyzer plugin.

Uses tree-sitter to extract functions, classes, methods, and imports
from Python source files. Registered as the 'py' analyzer via entry points.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from contracts.interfaces import DependencyEdge, Symbol

_LANGUAGE = Language(tspython.language())
_PARSER = Parser(_LANGUAGE)


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


def _walk(
    node: Node,
    results: list[Symbol | DependencyEdge],
    file: Path,
    current_func: str | None = None,
) -> None:
    """Recursively walk the AST and collect symbols and edges."""
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
        # Recurse into body with this function as the enclosing scope
        if block_node:
            _walk(block_node, results, file, current_func=name)
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
        if block_node:
            _walk(block_node, results, file, current_func=current_func)
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
            _walk(child, results, file, current_func)
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
        _walk(child, results, file, current_func)


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
        _walk(tree.root_node, results, path)
        return results
