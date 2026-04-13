"""context-router-language-dotnet: C#/.NET language analyzer plugin.

Uses tree-sitter to extract namespaces, classes, methods, properties, and
call edges from C# source files. ASP.NET and test framework attributes are
detected and tagged.
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

# Common .NET / BCL method names that pollute call-edge graphs
_DOTNET_BUILTIN_NAMES: frozenset[str] = frozenset({
    "ToString", "Equals", "GetHashCode", "CompareTo", "Clone",
    "GetType", "Dispose", "Finalize",
    "Add", "Remove", "Contains", "Clear", "Count",
    "Where", "Select", "FirstOrDefault", "ToList", "ToArray",
    "Any", "All", "OrderBy", "GroupBy", "Join",
    "Console", "WriteLine", "Write", "ReadLine",
    "Task", "Run", "WhenAll", "WhenAny", "FromResult",
    "Assert", "Equal", "NotEqual", "True", "False", "NotNull", "Null",
})


def _text(node: Node) -> str:
    """Return the decoded text of a tree-sitter node."""
    return (node.text or b"").decode("utf-8", errors="replace")


def _first_child_of_type(node: Node, *types: str) -> Node | None:
    """Return the first direct child whose type is in types."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _extract_invocation_name(node: Node) -> str:
    """Extract the called method name from an invocation_expression node."""
    # C# invocation: expr.Method(...) or Method(...)
    # The tree is: invocation_expression → member_access_expression → identifier
    # or directly invocation_expression → identifier
    for child in node.children:
        if child.type == "member_access_expression":
            # rightmost identifier is the method name
            ident = None
            for sub in child.children:
                if sub.type == "identifier":
                    ident = sub
            if ident:
                return _text(ident)
        if child.type == "identifier":
            return _text(child)
    return ""


def _collect_attributes(node: Node) -> list[str]:
    """Return attribute names from attribute_list siblings before node."""
    attrs: list[str] = []
    if node.parent is None:
        return attrs
    siblings = node.parent.children
    try:
        idx = siblings.index(node)
    except ValueError:
        return attrs
    for sib in siblings[:idx]:
        if sib.type == "attribute_list":
            for attr in sib.children:
                if attr.type == "attribute":
                    name_node = _first_child_of_type(attr, "identifier", "qualified_name")
                    if name_node:
                        attrs.append(_text(name_node))
    return attrs


def _walk(
    node: Node,
    results: list[Symbol | DependencyEdge],
    file: Path,
    current_method: str | None = None,
) -> None:
    """Recursively walk the C# AST and collect symbols and edges."""

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
            _walk(body, results, file, current_method)
        return

    if node.type in ("class_declaration", "interface_declaration",
                      "struct_declaration", "record_declaration"):
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        attrs = _collect_attributes(node)
        tags: list[str] = []
        if any(a in _ASPNET_ATTRIBUTES for a in attrs):
            tags.append("controller")
        kind_word = node.type.split("_")[0]
        # Store attributes in signature for visibility
        attrs_str = ", ".join(f"[{a}]" for a in attrs) if attrs else ""
        signature = f"{attrs_str} {kind_word} {name}".strip() if attrs_str else f"{kind_word} {name}"
        results.append(
            Symbol(
                name=name,
                kind="class",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="csharp",
                signature=signature,
            )
        )
        body = _first_child_of_type(node, "declaration_list")
        if body:
            _walk(body, results, file, current_method)
        return

    if node.type == "method_declaration":
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        attrs = _collect_attributes(node)
        tags: list[str] = []
        if any(a in _TEST_ATTRIBUTES for a in attrs):
            tags.append("test")
        return_type = _first_child_of_type(node, "predefined_type", "identifier",
                                            "nullable_type", "generic_name")
        attrs_str = ", ".join(f"[{a}]" for a in attrs) if attrs else ""
        sig = f"{_text(return_type) if return_type else 'void'} {name}()"
        if attrs_str:
            sig = f"{attrs_str} {sig}"
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
        # Recurse into method body with this method as context
        body = _first_child_of_type(node, "block")
        if body:
            _walk(body, results, file, name)
        return

    if node.type == "property_declaration":
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        type_node = _first_child_of_type(node, "predefined_type", "identifier",
                                          "nullable_type", "generic_name")
        type_str = _text(type_node) if type_node else "object"
        results.append(
            Symbol(
                name=name,
                kind="property",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="csharp",
                signature=f"{type_str} {name} {{ get; set; }}",
            )
        )
        return

    if node.type == "using_directive":
        # using System; / using System.Collections.Generic; → DependencyEdge
        name_node = _first_child_of_type(node, "identifier", "qualified_name")
        if name_node:
            full_name = _text(name_node)
            leaf = full_name.split(".")[-1]
            results.append(
                DependencyEdge(
                    from_symbol=str(file),
                    to_symbol=leaf,
                    edge_type="imports",
                )
            )
        return

    if node.type == "invocation_expression" and current_method is not None:
        called = _extract_invocation_name(node)
        if called and called not in _DOTNET_BUILTIN_NAMES:
            results.append(
                DependencyEdge(
                    from_symbol=current_method,
                    to_symbol=called,
                    edge_type="calls",
                )
            )
        # Recurse for nested invocations
        for child in node.children:
            _walk(child, results, file, current_method)
        return

    for child in node.children:
        _walk(child, results, file, current_method)


class DotnetAnalyzer:
    """Language analyzer for C# source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'cs'. Extracts namespaces, classes, methods, properties,
    using-directive import edges, and method-call edges.
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
