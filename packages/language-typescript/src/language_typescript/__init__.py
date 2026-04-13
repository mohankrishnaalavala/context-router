"""context-router-language-typescript: TypeScript/JavaScript language analyzer plugin.

Uses tree-sitter to extract functions, classes, interfaces, imports, and call
edges from TypeScript and TSX source files.
"""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol

try:
    import tree_sitter_typescript as tsts
    from tree_sitter import Language, Node, Parser

    _LANGUAGE_TS = Language(tsts.language_typescript())
    _LANGUAGE_TSX = Language(tsts.language_tsx())
    _TREE_SITTER_AVAILABLE = True
except Exception:  # pragma: no cover — optional dep
    _TREE_SITTER_AVAILABLE = False
    Node = object  # type: ignore[misc,assignment]

# Built-ins to skip for call edges
_BUILTINS = frozenset(
    {
        "console",
        "Math",
        "JSON",
        "Object",
        "Array",
        "String",
        "Number",
        "Boolean",
        "Promise",
        "setTimeout",
        "setInterval",
        "clearTimeout",
        "clearInterval",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "require",
        "module",
        "exports",
        "process",
        "Buffer",
    }
)


def _text(node: object) -> str:
    """Return UTF-8 text of a tree-sitter node."""
    return node.text.decode("utf-8") if node.text else ""  # type: ignore[attr-defined]


def _child_by_field(node: object, field: str) -> object | None:
    """Return child node by field name, with None safety."""
    try:
        return node.child_by_field_name(field)  # type: ignore[attr-defined]
    except Exception:
        return None


def _first_child_of_type(node: object, node_type: str) -> object | None:
    """Return first child whose type matches node_type."""
    for child in node.children:  # type: ignore[attr-defined]
        if child.type == node_type:
            return child
    return None


def _walk_ts(
    node: object,
    results: list[Symbol | DependencyEdge],
    file: Path,
    current_func: str | None = None,
) -> None:
    """Recursively walk a TypeScript tree-sitter node tree.

    Args:
        node: Current tree-sitter Node.
        results: Accumulator list for Symbol and DependencyEdge objects.
        file: Path of the file being analyzed.
        current_func: Name of the enclosing function/method, if any.
    """
    node_type = node.type  # type: ignore[attr-defined]

    if node_type == "function_declaration":
        name_node = _child_by_field(node, "name")
        if name_node:
            name = _text(name_node)
            start = node.start_point[0] + 1  # type: ignore[index]
            end = node.end_point[0] + 1  # type: ignore[index]
            results.append(
                Symbol(
                    name=name,
                    kind="function",
                    file=file,
                    line_start=start,
                    line_end=end,
                    language="typescript",
                )
            )
            for child in node.children:  # type: ignore[attr-defined]
                _walk_ts(child, results, file, current_func=name)
            return

    if node_type == "method_definition":
        name_node = _child_by_field(node, "name")
        if name_node:
            name = _text(name_node)
            start = node.start_point[0] + 1  # type: ignore[index]
            end = node.end_point[0] + 1  # type: ignore[index]
            results.append(
                Symbol(
                    name=name,
                    kind="function",
                    file=file,
                    line_start=start,
                    line_end=end,
                    language="typescript",
                )
            )
            for child in node.children:  # type: ignore[attr-defined]
                _walk_ts(child, results, file, current_func=name)
            return

    if node_type == "class_declaration":
        name_node = _child_by_field(node, "name")
        if name_node:
            name = _text(name_node)
            start = node.start_point[0] + 1  # type: ignore[index]
            end = node.end_point[0] + 1  # type: ignore[index]
            results.append(
                Symbol(
                    name=name,
                    kind="class",
                    file=file,
                    line_start=start,
                    line_end=end,
                    language="typescript",
                )
            )
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(child, results, file, current_func)
        return

    if node_type == "interface_declaration":
        name_node = _child_by_field(node, "name")
        if name_node:
            name = _text(name_node)
            start = node.start_point[0] + 1  # type: ignore[index]
            end = node.end_point[0] + 1  # type: ignore[index]
            results.append(
                Symbol(
                    name=name,
                    kind="interface",
                    file=file,
                    line_start=start,
                    line_end=end,
                    language="typescript",
                )
            )
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(child, results, file, current_func)
        return

    if node_type == "import_statement":
        # import { foo } from 'bar'  /  import foo from 'bar'
        source_node = _child_by_field(node, "source")
        if source_node:
            module = _text(source_node).strip("'\"")
            results.append(
                DependencyEdge(
                    from_symbol=str(file),
                    to_symbol=module,
                    edge_type="imports",
                )
            )
        return

    if node_type == "call_expression" and current_func is not None:
        func_node = _child_by_field(node, "function")
        called = ""
        if func_node is not None:
            ft = func_node.type  # type: ignore[attr-defined]
            if ft == "identifier":
                called = _text(func_node)
            elif ft == "member_expression":
                prop = _child_by_field(func_node, "property")
                called = _text(prop) if prop else ""

        if called and called not in _BUILTINS:
            results.append(
                DependencyEdge(
                    from_symbol=current_func,
                    to_symbol=called,
                    edge_type="calls",
                )
            )
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(child, results, file, current_func)
        return

    # Default: recurse into children
    for child in node.children:  # type: ignore[attr-defined]
        _walk_ts(child, results, file, current_func)


class TypeScriptAnalyzer:
    """Language analyzer for TypeScript and JavaScript source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with keys 'ts', 'tsx', and 'js'.  Uses tree-sitter to extract
    functions, classes, interfaces, imports, and call edges.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a TypeScript/JavaScript source file and return symbols and edges.

        Args:
            path: Absolute path to the .ts / .tsx / .js file.

        Returns:
            List of Symbol and DependencyEdge instances, or empty list if the
            file cannot be read or tree-sitter is unavailable.
        """
        if not _TREE_SITTER_AVAILABLE:
            return []

        suffix = path.suffix.lower()
        language = _LANGUAGE_TSX if suffix == ".tsx" else _LANGUAGE_TS

        try:
            source = path.read_bytes()
        except OSError:
            return []

        parser = Parser(language)
        tree = parser.parse(source)
        results: list[Symbol | DependencyEdge] = []
        _walk_ts(tree.root_node, results, path)
        return results
