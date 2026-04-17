"""context-router-language-java: Java language analyzer plugin.

Uses tree-sitter to extract classes, interfaces, methods, imports, call
edges, and inheritance / test-linkage edges from Java source files.
Spring annotations are tagged for detection.

v3 phase3/edge-kinds-extended: emits ``extends`` (class→superclass and
interface→super-interfaces), ``implements`` (class→interface), and
``tested_by`` (source method → test method) edges to match the CRG
edge-type vocabulary and unlock downstream ranking / audit features.
"""

from __future__ import annotations

import sys
from pathlib import Path

import tree_sitter_java as tsjava
from tree_sitter import Language, Node, Parser

from contracts.interfaces import DependencyEdge, Symbol

_LANGUAGE = Language(tsjava.language())
_PARSER = Parser(_LANGUAGE)

_SPRING_ANNOTATIONS = {
    "RestController", "Controller", "Service", "Repository",
    "Component", "SpringBootApplication", "RequestMapping",
}
_TEST_SUFFIXES = ("Test", "Tests", "IT", "Spec")

# Common JDK method names that pollute call-edge graphs
_JAVA_BUILTIN_NAMES: frozenset[str] = frozenset({
    "toString", "equals", "hashCode", "compareTo", "clone",
    "getClass", "notify", "notifyAll", "wait", "finalize",
    "println", "print", "printf", "format", "append",
    "length", "size", "get", "set", "add", "remove", "contains",
    "put", "putAll", "values", "keySet", "entrySet", "isEmpty",
    "stream", "collect", "map", "filter", "forEach", "reduce",
    "parseInt", "valueOf", "of", "asList", "toArray",
})


def _is_test_file(file: Path) -> bool:
    """Return True if *file* looks like a Java test file by naming convention."""
    stem = file.stem
    return (
        stem.endswith("Test")
        or stem.endswith("Tests")
        or stem.endswith("IT")
        or stem.endswith("Spec")
    )


def _sut_class_from_test_stem(stem: str) -> str | None:
    """Return the inferred class-under-test name from a test file's stem.

    Examples:
      ``PetControllerTests`` → ``PetController``
      ``OwnerControllerTest`` → ``OwnerController``
      ``CrashControllerIntegrationTests`` → ``CrashControllerIntegration``
      ``I18nPropertiesSyncTest`` → ``I18nPropertiesSync``
      ``PetClinicIT`` → ``PetClinic``
    """
    for suffix in ("Tests", "Test", "IT", "Spec"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            return stem[: -len(suffix)]
    return None


def _text(node: Node) -> str:
    """Return the decoded text of a tree-sitter node."""
    return (node.text or b"").decode("utf-8", errors="replace")


def _first_child_of_type(node: Node, *types: str) -> Node | None:
    """Return the first direct child whose type is in types."""
    for child in node.children:
        if child.type in types:
            return child
    return None


def _collect_annotations(node: Node) -> list[str]:
    """Collect annotation identifier names from a declaration's ``modifiers`` node.

    Tree-sitter-java attaches the ``modifiers`` node as a direct child of the
    declaration, containing both ``annotation`` and ``marker_annotation`` nodes.
    Older grammar versions may expose it as a preceding sibling — we scan both.
    """
    annotations: list[str] = []

    def _scan_modifiers(mods: Node) -> None:
        for mod in mods.children:
            if mod.type in ("annotation", "marker_annotation"):
                name_node = _first_child_of_type(mod, "identifier")
                if name_node:
                    annotations.append(_text(name_node))

    # Direct child (most tree-sitter-java versions)
    for child in node.children:
        if child.type == "modifiers":
            _scan_modifiers(child)

    # Preceding sibling (older grammar variants)
    if node.parent is not None:
        siblings = node.parent.children
        try:
            idx = siblings.index(node)
        except ValueError:
            idx = -1
        for sib in siblings[:idx]:
            if sib.type == "modifiers":
                _scan_modifiers(sib)

    # Dedupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for name in annotations:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _extract_javadoc(node: Node) -> str:
    """Return the JavaDoc comment immediately preceding node, or empty string."""
    if node.parent is None:
        return ""
    siblings = node.parent.children
    try:
        idx = siblings.index(node)
    except ValueError:
        return ""
    for sib in reversed(siblings[:idx]):
        if sib.type == "block_comment":
            raw = _text(sib)
            if raw.startswith("/**"):
                # Strip /** ... */ markers and leading * lines
                lines = [
                    line.strip().lstrip("*").strip()
                    for line in raw[3:-2].splitlines()
                ]
                return " ".join(l for l in lines if l)
        elif sib.type not in ("modifiers", "line_comment"):
            break
    return ""


def _extract_type_names(node: Node) -> list[str]:
    """Return leaf type names from a ``type_list`` / ``super_interfaces`` / etc.

    Walks all descendants, returning each ``type_identifier``'s text.  Generic
    arguments (``type_arguments``) are skipped so that ``JpaRepository<X, Y>``
    contributes only ``JpaRepository``.
    """
    names: list[str] = []

    def _rec(n: Node) -> None:
        if n.type == "type_arguments":
            return  # don't recurse into generic params
        if n.type == "type_identifier":
            names.append(_text(n))
            return
        for c in n.children:
            _rec(c)

    _rec(node)
    return names


def _emit_inheritance_edges(
    node: Node,
    class_name: str,
    results: list[Symbol | DependencyEdge],
) -> None:
    """Emit ``extends`` / ``implements`` edges for a class/interface declaration.

    * ``class_declaration``: ``superclass`` child → one ``extends`` edge;
      ``super_interfaces`` child → one ``implements`` edge per interface.
    * ``interface_declaration``: ``extends_interfaces`` child → one
      ``extends`` edge per super-interface (interfaces can multi-inherit).
    """
    if node.type == "class_declaration":
        super_node = _first_child_of_type(node, "superclass")
        if super_node:
            for parent in _extract_type_names(super_node):
                results.append(
                    DependencyEdge(
                        from_symbol=class_name,
                        to_symbol=parent,
                        edge_type="extends",
                    )
                )
        impl_node = _first_child_of_type(node, "super_interfaces")
        if impl_node:
            for iface in _extract_type_names(impl_node):
                results.append(
                    DependencyEdge(
                        from_symbol=class_name,
                        to_symbol=iface,
                        edge_type="implements",
                    )
                )
    elif node.type == "interface_declaration":
        ext_node = _first_child_of_type(node, "extends_interfaces")
        if ext_node:
            for parent in _extract_type_names(ext_node):
                results.append(
                    DependencyEdge(
                        from_symbol=class_name,
                        to_symbol=parent,
                        edge_type="extends",
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
    """Recursively walk the Java AST and collect symbols and edges.

    ``sut_name`` is the inferred class-under-test when *file* is a test file.
    ``has_emitted_test_edge`` is a single-element list used as a mutable flag
    so nested recursion can record whether any ``tested_by`` edge was emitted
    for this file (used for the silent-failure debug message).
    """

    if node.type in ("class_declaration", "interface_declaration", "enum_declaration",
                     "annotation_type_declaration"):
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        # P2-5: surface every annotation name in the signature so BM25 can
        # discover Spring / JPA / JUnit patterns without a hardcoded list.
        annotations = _collect_annotations(node)
        annotation_prefix = " ".join(f"@{a}" for a in annotations)
        # v3 phase1/interface-kind-label: emit the correct kind per node type.
        # Previously every type declaration was flattened to kind='class',
        # which broke ranking for Java-heavy repos that distinguish by kind.
        # Enum extraction is completed more fully in Phase 3
        # (`enum-symbols-extracted`); the label alone is emitted here.
        _JAVA_KIND_BY_NODE = {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "annotation_type_declaration": "annotation",
        }
        kind = _JAVA_KIND_BY_NODE[node.type]
        # Signature base word tracks the kind so BM25 / signature display stay honest.
        base = kind if kind != "annotation" else "@interface"
        signature = f"{annotation_prefix} {base} {name}".strip() if annotation_prefix else f"{base} {name}"
        results.append(
            Symbol(
                name=name,
                kind=kind,
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                signature=signature,
            )
        )
        # v3 phase3/edge-kinds-extended: emit inheritance edges.
        if node.type in ("class_declaration", "interface_declaration"):
            _emit_inheritance_edges(node, name, results)
        body = _first_child_of_type(node, "class_body", "interface_body",
                                     "enum_body", "annotation_type_body")
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

    if node.type in ("method_declaration", "constructor_declaration"):
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        annotations = _collect_annotations(node)
        annotation_prefix = " ".join(f"@{a}" for a in annotations)
        raw_sig = _text(node).split("{")[0].strip()
        signature = (annotation_prefix + " " + raw_sig).strip() if annotation_prefix else raw_sig
        docstring = _extract_javadoc(node)
        kind = "constructor" if node.type == "constructor_declaration" else "method"
        results.append(
            Symbol(
                name=name,
                kind=kind,
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                signature=signature,
                docstring=docstring,
            )
        )
        # v3 phase3/edge-kinds-extended: emit ``tested_by`` when inside a test
        # class whose SUT resolves via naming.  Edge direction: SUT (source) →
        # test method (target) — matches CRG's TESTED_BY convention.  The test
        # method must be annotated with @Test (JUnit 4 / 5) to avoid picking
        # up helper/setup methods like ``@BeforeEach setUp``.
        if (
            node.type == "method_declaration"
            and sut_name is not None
            and current_class is not None
            and "Test" in annotations
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
        body = _first_child_of_type(node, "block", "constructor_body")
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

    if node.type == "import_declaration":
        # import com.example.UserService; → DependencyEdge
        pkg_node = _first_child_of_type(node, "scoped_identifier", "identifier")
        if pkg_node:
            full_name = _text(pkg_node)
            leaf = full_name.split(".")[-1]
            results.append(
                DependencyEdge(
                    from_symbol=str(file),
                    to_symbol=leaf,
                    edge_type="imports",
                )
            )
        return

    if node.type == "method_invocation" and current_method is not None:
        # Capture calls: foo.bar() or bar() inside a method body
        # The method name is the last identifier child before the argument_list
        name_node = None
        for child in node.children:
            if child.type == "identifier":
                name_node = child
        called = _text(name_node) if name_node else ""
        if called and called not in _JAVA_BUILTIN_NAMES:
            results.append(
                DependencyEdge(
                    from_symbol=current_method,
                    to_symbol=called,
                    edge_type="calls",
                )
            )
        # Still recurse in case of nested calls
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


class JavaAnalyzer:
    """Language analyzer for Java source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'java'. Extracts classes, methods, import edges, and
    method-call edges.
    """

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        """Analyze a Java source file and return symbols and edges.

        Args:
            path: Absolute path to the .java file.

        Returns:
            List of Symbol and DependencyEdge objects.
        """
        try:
            source = path.read_bytes()
        except OSError:
            return []

        tree = _PARSER.parse(source)
        results: list[Symbol | DependencyEdge] = []

        # v3 phase3/edge-kinds-extended: infer the class-under-test for test
        # files so the walker can emit ``tested_by`` edges.  If resolution
        # fails, record the file for a silent-failure debug note.
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

        # Silent-failure rule: a test file yielded no tested_by edges — log a
        # debug-level note to stderr so operators can audit the gap.  Not a
        # warning (low signal), but not silent either.
        if _is_test_file(path) and not has_emitted_test_edge[0]:
            print(
                f"[language-java] debug: could not resolve SUT for test file {path}",
                file=sys.stderr,
            )

        return results
