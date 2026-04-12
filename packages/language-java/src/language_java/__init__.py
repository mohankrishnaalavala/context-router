"""context-router-language-java: Java language analyzer plugin.

Uses tree-sitter to extract classes, interfaces, methods, and imports
from Java source files. Spring annotations are tagged for detection.
"""

from __future__ import annotations

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
    """Collect annotation names from the siblings before a declaration node."""
    annotations: list[str] = []
    if node.parent is None:
        return annotations
    siblings = node.parent.children
    idx = siblings.index(node)
    for sib in siblings[:idx]:
        if sib.type == "modifiers":
            for mod in sib.children:
                if mod.type == "annotation":
                    name_node = _first_child_of_type(mod, "identifier")
                    if name_node:
                        annotations.append(_text(name_node))
    return annotations


def _walk(node: Node, results: list[Symbol | DependencyEdge], file: Path) -> None:
    """Recursively walk the Java AST and collect symbols."""

    if node.type in ("class_declaration", "interface_declaration", "enum_declaration",
                     "annotation_type_declaration"):
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        annotations = _collect_annotations(node)
        tags: list[str] = []
        if any(a in _SPRING_ANNOTATIONS for a in annotations):
            tags.append("spring")
        if any(name.endswith(s) for s in _TEST_SUFFIXES):
            tags.append("test")
        signature = f"class {name}"
        if node.type == "interface_declaration":
            signature = f"interface {name}"
        results.append(
            Symbol(
                name=name,
                kind="class",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                signature=signature,
            )
        )
        # Recurse into class body
        body = _first_child_of_type(node, "class_body", "interface_body",
                                     "enum_body", "annotation_type_body")
        if body:
            _walk(body, results, file)
        return

    if node.type == "method_declaration":
        name_node = _first_child_of_type(node, "identifier")
        name = _text(name_node) if name_node else "<unknown>"
        signature = _text(node).split("{")[0].strip()
        results.append(
            Symbol(
                name=name,
                kind="method",
                file=file,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language="java",
                signature=signature,
            )
        )
        return

    if node.type == "import_declaration":
        # import java.util.List;
        pkg_node = _first_child_of_type(node, "scoped_identifier", "identifier")
        if pkg_node:
            module = _text(pkg_node)
            results.append(
                Symbol(
                    name=module,
                    kind="import",
                    file=file,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="java",
                    signature=_text(node).strip(),
                )
            )
        return

    for child in node.children:
        _walk(child, results, file)


class JavaAnalyzer:
    """Language analyzer for Java source files.

    Registered under the 'context_router.language_analyzers' entry-points
    group with key 'java'. Extracts classes, methods, and import edges.
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
        _walk(tree.root_node, results, path)
        return results
