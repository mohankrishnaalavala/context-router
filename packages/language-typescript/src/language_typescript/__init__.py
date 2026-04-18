"""context-router-language-typescript: TypeScript/JavaScript language analyzer plugin.

Uses tree-sitter to extract functions, classes, interfaces, imports, call
edges, and inheritance / test-linkage edges from TypeScript and TSX source
files.

v3 phase3/edge-kinds-extended: emits ``extends`` (class → base class,
interface → super-interfaces), ``implements`` (class → interface), and
``tested_by`` (source symbol → test symbol via ``*.test.ts`` / ``*.spec.ts``
files that import source symbols) edges.
"""

from __future__ import annotations

import sys
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


def _looks_like_test_name(name: str) -> bool:
    """Heuristic: function names emitted inside ``it(...)``/``test(...)`` blocks
    are often anonymous arrow functions.  For named symbols we look for
    common prefixes (``test``, ``it``, ``should``).
    """
    if not name:
        return False
    if name.startswith("test") or name.startswith("it_") or name.startswith("should"):
        return True
    # Explicit helper: Jest / Vitest describe+it generate no named func, but
    # the invocation identifier is ``test`` / ``it``.  Callers of
    # ``_looks_like_test_name`` apply this only when ``current_func`` has a
    # name — so we also trust any top-level test function that imports real
    # symbols.
    return False


def _is_test_file(file: Path) -> bool:
    """Return True if *file* is a TS/JS test file by naming convention.

    Matches ``*.test.ts``, ``*.test.tsx``, ``*.test.js``, ``*.spec.ts``,
    ``*.spec.tsx``, ``*.spec.js``.  A ``__tests__`` directory also counts.
    """
    suffixes = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
    if file.suffix not in suffixes:
        return False
    stem = file.stem  # "foo.test" for foo.test.ts
    return (
        stem.endswith(".test")
        or stem.endswith(".spec")
        or any(part == "__tests__" for part in file.parts)
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


def _ts_type_names(node: object) -> list[str]:
    """Return identifier names from a TS clause (extends_clause / implements_clause).

    Handles ``identifier``, ``type_identifier``, and dotted ``member_expression``
    (``other.module.Base`` → ``Base``).  Generic arguments are skipped —
    ``Foo<T>`` contributes ``Foo`` only.
    """
    names: list[str] = []
    for c in node.children:  # type: ignore[attr-defined]
        t = c.type  # type: ignore[attr-defined]
        if t in ("identifier", "type_identifier"):
            names.append(_text(c))
        elif t == "member_expression":
            # property side is the leaf (e.g. "Base" in "other.module.Base")
            prop = _child_by_field(c, "property")
            if prop:
                names.append(_text(prop))
        elif t == "generic_type":
            # generic_type has a "name" field with the type_identifier
            name_sub = _child_by_field(c, "name")
            if name_sub:
                names.append(_text(name_sub))
            else:
                # Fallback: first type_identifier child
                for sub in c.children:  # type: ignore[attr-defined]
                    if sub.type in ("identifier", "type_identifier"):  # type: ignore[attr-defined]
                        names.append(_text(sub))
                        break
        # Skip commas and keywords like ``extends``/``implements``.
    return names


def _emit_ts_inheritance_edges(
    node: object,
    class_name: str,
    results: list[Symbol | DependencyEdge],
) -> None:
    """Emit ``extends`` / ``implements`` edges for a TS class/interface declaration.

    * ``class_declaration`` with ``class_heritage`` child: one ``extends``
      edge from ``extends_clause``, one ``implements`` edge per identifier
      in ``implements_clause``.
    * ``interface_declaration`` with ``extends_type_clause``: one ``extends``
      edge per super-interface.
    """
    nt = node.type  # type: ignore[attr-defined]
    if nt == "class_declaration":
        heritage = _first_child_of_type(node, "class_heritage")
        if heritage is None:
            return
        for sub in heritage.children:  # type: ignore[attr-defined]
            st = sub.type  # type: ignore[attr-defined]
            if st == "extends_clause":
                for base in _ts_type_names(sub):
                    results.append(
                        DependencyEdge(
                            from_symbol=class_name,
                            to_symbol=base,
                            edge_type="extends",
                        )
                    )
            elif st == "implements_clause":
                for iface in _ts_type_names(sub):
                    results.append(
                        DependencyEdge(
                            from_symbol=class_name,
                            to_symbol=iface,
                            edge_type="implements",
                        )
                    )
    elif nt == "interface_declaration":
        ext = _first_child_of_type(node, "extends_type_clause")
        if ext is None:
            return
        for base in _ts_type_names(ext):
            results.append(
                DependencyEdge(
                    from_symbol=class_name,
                    to_symbol=base,
                    edge_type="extends",
                )
            )


def _walk_ts(
    node: object,
    results: list[Symbol | DependencyEdge],
    file: Path,
    current_func: str | None = None,
    is_test_file: bool = False,
    imported_names: set[str] | None = None,
    has_emitted_test_edge: list[bool] | None = None,
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
                _walk_ts(
                    child,
                    results,
                    file,
                    current_func=name,
                    is_test_file=is_test_file,
                    imported_names=imported_names,
                    has_emitted_test_edge=has_emitted_test_edge,
                )
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
                _walk_ts(
                    child,
                    results,
                    file,
                    current_func=name,
                    is_test_file=is_test_file,
                    imported_names=imported_names,
                    has_emitted_test_edge=has_emitted_test_edge,
                )
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
            # v3 phase3/edge-kinds-extended: emit inheritance edges.
            _emit_ts_inheritance_edges(node, name, results)
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(
                child,
                results,
                file,
                current_func,
                is_test_file=is_test_file,
                imported_names=imported_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
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
            _walk_ts(
                child,
                results,
                file,
                current_func,
                is_test_file=is_test_file,
                imported_names=imported_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
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
            # v3 phase3/edge-kinds-extended: interfaces can extend multiple
            # super-interfaces via an ``extends_type_clause``.
            _emit_ts_inheritance_edges(node, name, results)
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(
                child,
                results,
                file,
                current_func,
                is_test_file=is_test_file,
                imported_names=imported_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
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
            _walk_ts(
                child,
                results,
                file,
                current_func,
                is_test_file=is_test_file,
                imported_names=imported_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
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
                    _walk_ts(
                        child,
                        results,
                        file,
                        current_func=name,
                        is_test_file=is_test_file,
                        imported_names=imported_names,
                        has_emitted_test_edge=has_emitted_test_edge,
                    )
                return
        # Default: recurse for destructuring / non-arrow declarations
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(
                child,
                results,
                file,
                current_func,
                is_test_file=is_test_file,
                imported_names=imported_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
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
        # v3 phase3/edge-kinds-extended: in a test file, record the
        # imported names so ``call_expression`` can later emit tested_by
        # edges when a test function invokes one of them.
        if is_test_file and imported_names is not None:
            import_clause = _first_child_of_type(node, "import_clause")
            if import_clause is not None:
                for c in import_clause.children:  # type: ignore[attr-defined]
                    ct = c.type  # type: ignore[attr-defined]
                    if ct == "identifier":
                        imported_names.add(_text(c))
                    elif ct == "named_imports":
                        for spec in c.children:  # type: ignore[attr-defined]
                            if spec.type == "import_specifier":  # type: ignore[attr-defined]
                                n = _child_by_field(spec, "name")
                                alias = _child_by_field(spec, "alias")
                                target = alias if alias else n
                                if target is not None:
                                    imported_names.add(_text(target))
                    elif ct == "namespace_import":
                        for sub in c.children:  # type: ignore[attr-defined]
                            if sub.type == "identifier":  # type: ignore[attr-defined]
                                imported_names.add(_text(sub))
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
            # v3 phase3/edge-kinds-extended: in a test file, if the caller
            # is a test function and the callee is an imported source
            # symbol, emit ``tested_by`` from the imported symbol → test
            # function.  This mirrors CRG's TESTED_BY semantics.
            if (
                is_test_file
                and imported_names is not None
                and called in imported_names
                and _looks_like_test_name(current_func)
            ):
                results.append(
                    DependencyEdge(
                        from_symbol=called,
                        to_symbol=current_func,
                        edge_type="tested_by",
                    )
                )
                if has_emitted_test_edge is not None:
                    has_emitted_test_edge[0] = True
        for child in node.children:  # type: ignore[attr-defined]
            _walk_ts(
                child,
                results,
                file,
                current_func,
                is_test_file=is_test_file,
                imported_names=imported_names,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return

    # Default: recurse into children
    for child in node.children:  # type: ignore[attr-defined]
        _walk_ts(
            child,
            results,
            file,
            current_func,
            is_test_file=is_test_file,
            imported_names=imported_names,
            has_emitted_test_edge=has_emitted_test_edge,
        )


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

        # v3 phase3/edge-kinds-extended: record whether *path* is a test
        # file so the walker can emit ``tested_by`` edges when a named
        # test function calls an imported source symbol.
        is_test = _is_test_file(path)
        imported_names: set[str] = set()
        has_emitted_test_edge: list[bool] = [False]

        _walk_ts(
            tree.root_node,
            results,
            path,
            is_test_file=is_test,
            imported_names=imported_names,
            has_emitted_test_edge=has_emitted_test_edge,
        )

        # Silent-failure rule: test file with imported source symbols but no
        # ``tested_by`` edges emitted — log a debug note so operators can
        # audit the gap without spamming a warning (low signal; many TS
        # suites use anonymous arrow callbacks).
        if is_test and imported_names and not has_emitted_test_edge[0]:
            print(
                f"[language-typescript] debug: could not emit tested_by for "
                f"test file {path} (no named test function invoking an "
                f"imported symbol)",
                file=sys.stderr,
            )

        return results
