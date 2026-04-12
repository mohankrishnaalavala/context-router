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


def _walk(node: Node, results: list[Symbol | DependencyEdge], file: Path) -> None:
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
        # Recurse into body (to catch nested/method defs)
        if block_node:
            _walk(block_node, results, file)
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
            _walk(block_node, results, file)
        return

    if node.type == "import_statement":
        # import os, import pathlib.Path
        for child in node.children:
            if child.type in ("dotted_name", "aliased_import"):
                module = _text(child).split(" as ")[0].strip()
                results.append(
                    Symbol(
                        name=module,
                        kind="import",
                        file=file,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        signature=_text(node),
                    )
                )
        return

    if node.type == "import_from_statement":
        # from pathlib import Path
        module_node = _first_child_of_type(node, "dotted_name", "relative_import")
        if module_node:
            module = _text(module_node)
            results.append(
                Symbol(
                    name=module,
                    kind="import",
                    file=file,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="python",
                    signature=_text(node),
                )
            )
        return

    # Recurse for all other node types
    for child in node.children:
        _walk(child, results, file)


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
