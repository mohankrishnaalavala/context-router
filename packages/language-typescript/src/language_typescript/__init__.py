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


def _collect_decorator_names(node: object) -> list[str]:
    """Return decorator identifier names attached to *node* (e.g. ``@Component``).

    Handles three common shapes produced by tree-sitter-typescript:
      * ``decorator(identifier)`` — bare ``@Inject``
      * ``decorator(call_expression(function=identifier))`` — ``@Component({...})``
      * ``decorator(call_expression(function=member_expression))`` — ``@ng.Component()``
    Decorators appear either as direct children of the declaration or as
    preceding siblings, depending on grammar version — we scan both.
    """
    names: list[str] = []
    candidates: list[object] = []
    # Direct children (tree-sitter-typescript typically attaches decorators here)
    for child in node.children:  # type: ignore[attr-defined]
        if child.type == "decorator":
            candidates.append(child)
    # Preceding siblings (older grammar shapes)
    parent = getattr(node, "parent", None)
    if parent is not None:
        try:
            idx = parent.children.index(node)  # type: ignore[attr-defined]
            for sib in parent.children[:idx]:  # type: ignore[attr-defined]
                if sib.type == "decorator":
                    candidates.append(sib)
        except (ValueError, AttributeError):
            pass

    for dec in candidates:
        inner: object | None = None
        for c in dec.children:  # type: ignore[attr-defined]
            if c.type in ("identifier", "call_expression", "member_expression"):
                inner = c
                break
        if inner is None:
            continue
        if inner.type == "identifier":  # type: ignore[attr-defined]
            names.append(_text(inner))
        elif inner.type == "call_expression":  # type: ignore[attr-defined]
            fn = _child_by_field(inner, "function")
            if fn is not None:
                if fn.type == "identifier":  # type: ignore[attr-defined]
                    names.append(_text(fn))
                elif fn.type == "member_expression":  # type: ignore[attr-defined]
                    prop = _child_by_field(fn, "property")
                    if prop:
                        names.append(_text(prop))
        elif inner.type == "member_expression":  # type: ignore[attr-defined]
            prop = _child_by_field(inner, "property")
            if prop:
                names.append(_text(prop))
    # Dedupe preserving order
    seen: set[str] = set()
    result: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            result.append(n)
    return result


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
            decorators = _collect_decorator_names(node)
            sig = " ".join(f"@{d}" for d in decorators) + f" {name}()" if decorators else ""
            results.append(
                Symbol(
                    name=name,
                    kind="function",
                    file=file,
                    line_start=start,
                    line_end=end,
                    language="typescript",
                    signature=sig.strip(),
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
            decorators = _collect_decorator_names(node)
            prefix = " ".join(f"@{d}" for d in decorators)
            signature = (prefix + " class " + name).strip() if prefix else f"class {name}"
            results.append(
                Symbol(
                    name=name,
                    kind="class",
                    file=file,
                    line_start=start,
                    line_end=end,
                    language="typescript",
                    signature=signature,
                )
            )
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(child, results, file, current_func)
        return

    if node_type == "enum_declaration":
        name_node = _child_by_field(node, "name")
        if name_node:
            name = _text(name_node)
            start = node.start_point[0] + 1  # type: ignore[index]
            end = node.end_point[0] + 1  # type: ignore[index]
            results.append(
                Symbol(
                    name=name,
                    kind="enum",
                    file=file,
                    line_start=start,
                    line_end=end,
                    language="typescript",
                    signature=f"enum {name}",
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

    if node_type == "type_alias_declaration":
        name_node = _child_by_field(node, "name")
        if name_node:
            name = _text(name_node)
            start = node.start_point[0] + 1  # type: ignore[index]
            end = node.end_point[0] + 1  # type: ignore[index]
            results.append(
                Symbol(
                    name=name,
                    kind="type",
                    file=file,
                    line_start=start,
                    line_end=end,
                    language="typescript",
                )
            )
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(child, results, file, current_func)
        return

    if node_type == "variable_declarator":
        # Capture arrow functions: const Foo = () => {...} / const Foo = async () => {...}
        name_node = _child_by_field(node, "name")
        value_node = _child_by_field(node, "value")
        if name_node and value_node and value_node.type in (  # type: ignore[attr-defined]
            "arrow_function", "function_expression"
        ):
            name = _text(name_node)
            if name and name[0].isalpha():  # skip destructuring patterns
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
                for child in value_node.children:  # type: ignore[attr-defined]
                    _walk_ts(child, results, file, current_func=name)
                return
        # Default: recurse for destructuring / non-arrow declarations
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
