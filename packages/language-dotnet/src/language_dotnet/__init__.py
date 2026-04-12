"""context-router-language-dotnet: C#/.NET language analyzer plugin.

Uses tree-sitter to extract namespaces, classes, methods, and using
directives from C# source files. ASP.NET and test framework attributes
are detected and tagged.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_c_sharp as tscs
from tree_sitter import Language, Node, Parser

from contracts.interfaces import DependencyEdge, Symbol

_LANGUAGE = Language(tscs.language())
_PARSER = Parser(_LANGUAGE)

_ASPNET_ATTRIBUTES = {"ApiController", "Controller", "Route", "HttpGet", "HttpPost",
                       "HttpPut", "HttpDelete", "Authorize"}
_TEST_ATTRIBUTES = {"Fact", "Theory", "Test", "TestMethod", "TestCase"}


def _text(node: Node) -> str:
    """Return the decoded text of a tree-sitter node."""
    return (node.text or b"").decode("utf-8", errors="replace")


def _first_child_of_type(node: Node, *types: str) -> Node | None:
    """Return the first direct child whose type is in types."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _walk(node: Node, results: list[Symbol | DependencyEdge], file: Path) -> None:
    """Recursively walk the C# AST and collect symbols."""

    if node.type == "namespace_declaration":
        name_node = _first_child_of_type(node, "identifier", "qualified_name")
        name = _text(name_node) if name_node else "<unknown>"
        results.append(
            Symbol(
                name=name,
                kind="namespace",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="csharp",
                signature=f"namespace {name}",
            )
        )
        body = _first_child_of_type(node, "declaration_list")
        if body:
            _walk(body, results, file)
        return

    if node.type in ("class_declaration", "interface_declaration",
                      "struct_declaration", "record_declaration"):
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        # Look for attribute lists before this node
        tags: list[str] = []
        if node.parent:
            siblings = node.parent.children
            try:
                idx = siblings.index(node)
                for sib in siblings[:idx]:
                    if sib.type == "attribute_list":
                        attr_text = _text(sib)
                        if any(a in attr_text for a in _ASPNET_ATTRIBUTES):
                            tags.append("controller")
            except ValueError:
                pass
        kind_word = node.type.split("_")[0]
        results.append(
            Symbol(
                name=name,
                kind="class",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="csharp",
                signature=f"{kind_word} {name}",
            )
        )
        body = _first_child_of_type(node, "declaration_list")
        if body:
            _walk(body, results, file)
        return

    if node.type == "method_declaration":
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        # Check if this is a test method
        tags: list[str] = []
        if node.parent:
            siblings = node.parent.children
            try:
                idx = siblings.index(node)
                for sib in siblings[:idx]:
                    if sib.type == "attribute_list":
                        attr_text = _text(sib)
                        if any(a in attr_text for a in _TEST_ATTRIBUTES):
                            tags.append("test")
            except ValueError:
                pass
        return_type = _first_child_of_type(node, "predefined_type", "identifier",
                                            "nullable_type", "generic_name")
        sig = f"{_text(return_type) if return_type else 'void'} {name}()"
        results.append(
            Symbol(
                name=name,
                kind="method",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="csharp",
                signature=sig,
            )
        )
        return

    if node.type == "using_directive":
        # using System; / using System.Collections.Generic;
        name_node = _first_child_of_type(node, "identifier", "qualified_name")
        if name_node:
            module = _text(name_node)
            results.append(
                Symbol(
                    name=module,
                    kind="import",
                    file=file,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="csharp",
                    signature=_text(node).strip(),
                )
            )
        return

    for child in node.children:
        _walk(child, results, file)


class DotnetAnalyzer:
    """Language analyzer for C# source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'cs'. Extracts namespaces, classes, methods, and usings.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a C# source file and return symbols and edges.

        Args:
            path: Absolute path to the .cs file.

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
