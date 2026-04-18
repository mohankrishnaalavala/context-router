"""context-router-language-dotnet: C#/.NET language analyzer plugin.

Uses tree-sitter to extract namespaces, classes, methods, properties, call
edges, and inheritance / test-linkage edges from C# source files.  ASP.NET
and test framework attributes are detected and tagged.

v3 phase3/edge-kinds-extended: emits ``extends`` (class/record → base
class), ``implements`` (class/record → interface), and ``tested_by``
(source method → test method) edges to match the CRG edge-type
vocabulary and unlock downstream ranking / audit features.
"""

from __future__ import annotations

import sys
from pathlib import Path

import tree_sitter_c_sharp as tscs
from contracts.interfaces import DependencyEdge, Symbol
from tree_sitter import Language, Node, Parser

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


def _is_test_file(file: Path) -> bool:
    """Return True if *file* looks like a C# test file by naming convention."""
    stem = file.stem
    return (
        stem.endswith("Tests")
        or stem.endswith("Test")
        or stem.endswith("Spec")
        or stem.startswith("Test")
    )


def _sut_class_from_test_stem(stem: str) -> str | None:
    """Return the inferred class-under-test name for a C# test file stem.

    Examples:
      ``UsersControllerTests`` → ``UsersController``
      ``OrderServiceTest`` → ``OrderService``
      ``TestOrderService`` → ``OrderService``
      ``OrderServiceSpec`` → ``OrderService``
    """
    for suffix in ("Tests", "Test", "Spec"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            return stem[: -len(suffix)]
    # xUnit-style prefix: TestFoo → Foo
    if stem.startswith("Test") and len(stem) > 4 and stem[4].isupper():
        return stem[4:]
    return None


def _looks_like_interface_name(name: str) -> bool:
    """C# convention: interface names start with uppercase ``I`` + uppercase letter."""
    return len(name) >= 2 and name[0] == "I" and name[1].isupper()


def _text(node: Node) -> str:
    """Return the decoded text of a tree-sitter node."""
    return (node.text or b"").decode("utf-8", errors="replace")


def _first_child_of_type(node: Node, *types: str) -> Node | None:
    """Return the first direct child whose type is in types."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _name_field_text(node: Node) -> str | None:
    """Return the text of *node*'s ``name`` field, if any.

    C# declarations (method / constructor / property / class / interface /
    record / struct / enum) expose their identifier via the ``name`` field
    in tree-sitter-c-sharp.  This is the canonical way to read the
    declared name — falling back to ``_first_child_of_type(node,
    "identifier")`` is unsafe for ``method_declaration`` because a custom
    return type (``public HttpClient GetClient()``) appears as an
    earlier ``identifier`` child and would shadow the method name.
    """
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _text(name_node)


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
    """Return attribute names attached to *node*.

    Handles two grammar shapes:
      1. ``attribute_list`` as a direct child of the declaration (current
         tree-sitter-c-sharp versions).
      2. ``attribute_list`` as a preceding sibling (older grammar variants).
    Emits each identifier from ``[A, B(args)]`` style attribute groups.
    """
    attrs: list[str] = []

    def _scan_attribute_list(al: Node) -> None:
        for attr in al.children:
            if attr.type == "attribute":
                name_node = _first_child_of_type(attr, "identifier", "qualified_name")
                if name_node:
                    attrs.append(_text(name_node))

    # Direct children (modern grammar)
    for child in node.children:
        if child.type == "attribute_list":
            _scan_attribute_list(child)

    # Preceding siblings (older grammar)
    if node.parent is not None:
        siblings = node.parent.children
        try:
            idx = siblings.index(node)
        except ValueError:
            idx = -1
        for sib in siblings[:idx]:
            if sib.type == "attribute_list":
                _scan_attribute_list(sib)

    # Dedupe preserving order
    seen: set[str] = set()
    result: list[str] = []
    for a in attrs:
        if a not in seen:
            seen.add(a)
            result.append(a)
    return result


def _base_list_names(node: Node) -> list[str]:
    """Return the identifier names in a C# ``base_list``.

    Generic types like ``JpaRepository<X, Y>`` become ``JpaRepository`` (the
    type_arguments subtree is skipped).  Separator tokens (``:``, ``,``) and
    whitespace are ignored.
    """
    names: list[str] = []
    for child in node.children:
        if child.type == "identifier":
            names.append(_text(child))
        elif child.type == "qualified_name":
            # Namespace.Foo → leaf Foo
            leaf = _text(child).split(".")[-1].strip()
            if leaf:
                names.append(leaf)
        elif child.type == "generic_name":
            ident = _first_child_of_type(child, "identifier")
            if ident:
                names.append(_text(ident))
    return names


def _emit_inheritance_edges(
    node: Node,
    class_name: str,
    results: list[Symbol | DependencyEdge],
) -> None:
    """Emit ``extends`` / ``implements`` edges for a C# type declaration.

    C# ``base_list`` does not syntactically distinguish the base class from
    implemented interfaces — the base class (if any) must come first.  We use
    two heuristics in order:

    1. For ``interface_declaration``: every entry is a super-interface →
       ``extends``.
    2. For ``class_declaration`` / ``record_declaration`` / ``struct``:
       the first non-``I[A-Z]*`` identifier is the base class → ``extends``.
       All others → ``implements``.  If every entry matches the interface
       naming pattern (``IFoo``), there is no base class: all become
       ``implements``.
    """
    base_list = _first_child_of_type(node, "base_list")
    if not base_list:
        return
    names = _base_list_names(base_list)
    if not names:
        return

    if node.type == "interface_declaration":
        for n in names:
            results.append(
                DependencyEdge(
                    from_symbol=class_name,
                    to_symbol=n,
                    edge_type="extends",
                )
            )
        return

    # class / record / struct
    extends_candidate: str | None = None
    implements_list: list[str] = []
    if not _looks_like_interface_name(names[0]):
        extends_candidate = names[0]
        implements_list = names[1:]
    else:
        implements_list = names
    if extends_candidate is not None:
        results.append(
            DependencyEdge(
                from_symbol=class_name,
                to_symbol=extends_candidate,
                edge_type="extends",
            )
        )
    for n in implements_list:
        results.append(
            DependencyEdge(
                from_symbol=class_name,
                to_symbol=n,
                edge_type="implements",
            )
        )


def _walk(
    node: Node,
    results: list[Symbol | DependencyEdge],
    file: Path,
    current_method: str | None = None,
    current_class: str | None = None,
    sut_name: str | None = None,
    has_emitted_test_edge: list[bool] | None = None,
) -> None:
    """Recursively walk the C# AST and collect symbols and edges.

    ``sut_name`` is the inferred class-under-test when *file* is a test
    file; used to emit ``tested_by`` edges from SUT → test methods.
    """

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
            _walk(
                body,
                results,
                file,
                current_method,
                current_class=current_class,
                sut_name=sut_name,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return

    if node.type in ("class_declaration", "interface_declaration",
                      "struct_declaration", "record_declaration",
                      "enum_declaration"):
        # v3 phase4/edge-source-resolution-fix: read the declared name
        # from the ``name`` field.  For these node types the first
        # ``identifier`` child is also the name (no preceding return
        # type), so behavior is unchanged — but this is the canonical
        # API and matches the method/constructor/property handlers.
        name = _name_field_text(node)
        if not name:
            name_node = _first_child_of_type(node, "identifier")
            name = _text(name_node) if name_node else "<unknown>"
        attrs = _collect_attributes(node)
        tags: list[str] = []
        if any(a in _ASPNET_ATTRIBUTES for a in attrs):
            tags.append("controller")
        # v3 phase1/interface-kind-label: emit the correct kind per node type.
        # Previously every type declaration was flattened to kind='class',
        # which hid interfaces and records from kind-based queries / ranking.
        # v3 phase3/enum-symbols-extracted: ``enum_declaration`` now also
        # emits kind='enum' so callers can filter by enumeration types.
        _DOTNET_KIND_BY_NODE = {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "struct_declaration": "struct",
            "record_declaration": "record",
            "enum_declaration": "enum",
        }
        kind = _DOTNET_KIND_BY_NODE[node.type]
        kind_word = kind  # Signature keyword mirrors the emitted kind.
        # Store attributes in signature for visibility
        attrs_str = ", ".join(f"[{a}]" for a in attrs) if attrs else ""
        signature = f"{attrs_str} {kind_word} {name}".strip() if attrs_str else f"{kind_word} {name}"
        results.append(
            Symbol(
                name=name,
                kind=kind,
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="csharp",
                signature=signature,
            )
        )
        # v3 phase3/edge-kinds-extended: emit inheritance edges.  ``struct``
        # types technically can implement interfaces but not inherit, so only
        # ``class``/``record``/``interface`` are covered.  For ``struct`` we
        # still emit ``implements`` via the shared helper (first entry is
        # treated as extends iff it doesn't look like an interface, which is
        # conservative — structs cannot extend in C#, so this is rare).
        if node.type in ("class_declaration", "interface_declaration",
                         "record_declaration", "struct_declaration"):
            _emit_inheritance_edges(node, name, results)
        body = _first_child_of_type(node, "declaration_list")
        if body:
            _walk(
                body,
                results,
                file,
                current_method,
                current_class=name,
                sut_name=sut_name,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return

    if node.type == "method_declaration":
        # v3 phase4/edge-source-resolution-fix: use the ``name`` field
        # instead of the first ``identifier`` child.  A custom return
        # type (e.g. ``public HttpClient GetClient()``) emits an
        # ``identifier`` child BEFORE the method name, which would
        # otherwise leak the return type into ``symbols.name`` (and in
        # turn mis-anchor ``tested_by`` targets and pollute the graph
        # with spurious ``kind='method'`` rows named ``Task``,
        # ``HttpClient``, etc.).
        name = _name_field_text(node)
        if not name:
            # Silent-failure rule: the parser should always populate the
            # ``name`` field for a method_declaration; if it does not,
            # something is structurally wrong — skip the symbol rather
            # than risk anchoring on the return type.
            print(
                f"[language-dotnet] debug: method_declaration without name field "
                f"at {file}:{node.start_point[0] + 1}",
                file=sys.stderr,
            )
            # Fall through: do not emit a method symbol with a bogus name.
            # We still recurse into the body so call edges are captured.
            body = _first_child_of_type(node, "block")
            if body:
                _walk(
                    body,
                    results,
                    file,
                    current_method=None,
                    current_class=current_class,
                    sut_name=sut_name,
                    has_emitted_test_edge=has_emitted_test_edge,
                )
            return
        attrs = _collect_attributes(node)
        # Return-type is the ``type`` field; fall back to the old
        # first-typed-child heuristic for signature display only (not
        # used for name extraction anymore).
        type_field = node.child_by_field_name("type")
        return_type = type_field or _first_child_of_type(
            node, "predefined_type", "identifier", "nullable_type", "generic_name"
        )
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
        # v3 phase3/edge-kinds-extended: emit ``tested_by`` when this method
        # is a test method ([Fact] / [Test] / [Theory] / [TestMethod] /
        # [TestCase]) inside a test file with a resolvable SUT.
        if (
            sut_name is not None
            and current_class is not None
            and any(a in _TEST_ATTRIBUTES for a in attrs)
        ):
            results.append(
                DependencyEdge(
                    from_symbol=sut_name,
                    to_symbol=name,
                    edge_type="tested_by",
                )
            )
            if has_emitted_test_edge is not None:
                has_emitted_test_edge[0] = True
        # Recurse into method body with this method as context
        body = _first_child_of_type(node, "block")
        if body:
            _walk(
                body,
                results,
                file,
                current_method=name,
                current_class=current_class,
                sut_name=sut_name,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return

    if node.type == "constructor_declaration":
        # v3 phase4/edge-source-resolution-fix: prefer the ``name`` field
        # for parity with method/class handlers.  Constructors have no
        # preceding return type, so the first-identifier heuristic also
        # returned the correct name — this is purely defensive.
        name = _name_field_text(node)
        if not name:
            name_node = _first_child_of_type(node, "identifier")
            name = _text(name_node) if name_node else "<unknown>"
        attrs = _collect_attributes(node)
        attrs_str = ", ".join(f"[{a}]" for a in attrs) if attrs else ""
        raw_sig = _text(node).split("{")[0].strip()
        sig = f"{attrs_str} {raw_sig}".strip() if attrs_str else raw_sig
        results.append(
            Symbol(
                name=name,
                kind="constructor",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="csharp",
                signature=sig,
            )
        )
        body = _first_child_of_type(node, "block")
        if body:
            _walk(
                body,
                results,
                file,
                current_method=name,
                current_class=current_class,
                sut_name=sut_name,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return

    if node.type == "property_declaration":
        # v3 phase4/edge-source-resolution-fix: prefer the ``name`` field
        # so a custom property type (``public HttpClient Client { get; }``)
        # does not mis-label the property with its return-type identifier.
        name = _name_field_text(node)
        if not name:
            name_node = _first_child_of_type(node, "identifier")
            name = _text(name_node) if name_node else "<unknown>"
        type_field = node.child_by_field_name("type")
        type_node = type_field or _first_child_of_type(
            node, "predefined_type", "identifier", "nullable_type", "generic_name"
        )
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
            _walk(
                child,
                results,
                file,
                current_method,
                current_class=current_class,
                sut_name=sut_name,
                has_emitted_test_edge=has_emitted_test_edge,
            )
        return

    for child in node.children:
        _walk(
            child,
            results,
            file,
            current_method,
            current_class=current_class,
            sut_name=sut_name,
            has_emitted_test_edge=has_emitted_test_edge,
        )


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

        # v3 phase3/edge-kinds-extended: infer the SUT for test files.
        sut_name: str | None = None
        if _is_test_file(path):
            sut_name = _sut_class_from_test_stem(path.stem)
        has_emitted_test_edge: list[bool] = [False]

        _walk(
            tree.root_node,
            results,
            path,
            sut_name=sut_name,
            has_emitted_test_edge=has_emitted_test_edge,
        )

        # Silent-failure rule: test file but no SUT resolved → debug note.
        if _is_test_file(path) and not has_emitted_test_edge[0]:
            print(
                f"[language-dotnet] debug: could not resolve SUT for test file {path}",
                file=sys.stderr,
            )

        return results
