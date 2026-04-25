"""context-router-language-ruby: Ruby language analyzer plugin.

Extracts methods (instance and singleton), classes, and modules using
tree-sitter. Registered as the ``rb`` analyzer via entry points.
"""
from __future__ import annotations

from pathlib import Path

import tree_sitter_ruby as tsruby
from tree_sitter import Language, Node, Parser

from contracts.interfaces import DependencyEdge, Symbol

_LANGUAGE = Language(tsruby.language())
_PARSER = Parser(_LANGUAGE)


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


class RubyAnalyzer:
    """Ruby analyzer — methods, classes, modules."""

    def _is_test_file(self, file: Path) -> bool:
        name, parts = file.name, file.parts
        return (
            name.endswith("_spec.rb")
            or name.startswith("test_")
            or "spec" in parts
            or "test" in parts
        )

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        try:
            source = path.read_bytes()
        except OSError:
            return []
        tree = _PARSER.parse(source)
        results: list[Symbol | DependencyEdge] = []
        self._walk(tree.root_node, path, results)
        return results

    def _walk(self, node: Node, path: Path, results: list) -> None:
        if node.type == "method":
            name_node = node.child_by_field_name("name")
            if name_node:
                results.append(Symbol(
                    name=_text(name_node),
                    kind="method",
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="rb",
                    signature=f"def {_text(name_node)}",
                ))

        elif node.type == "singleton_method":
            name_node = node.child_by_field_name("name")
            if name_node:
                results.append(Symbol(
                    name=_text(name_node),
                    kind="method",
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="rb",
                    signature=f"def self.{_text(name_node)}",
                ))

        elif node.type == "class":
            name_node = node.child_by_field_name("name")
            if name_node:
                results.append(Symbol(
                    name=_text(name_node),
                    kind="class",
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="rb",
                    signature=f"class {_text(name_node)}",
                ))

        elif node.type == "module":
            name_node = node.child_by_field_name("name")
            if name_node:
                results.append(Symbol(
                    name=_text(name_node),
                    kind="module",
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="rb",
                    signature=f"module {_text(name_node)}",
                ))

        for child in node.children:
            self._walk(child, path, results)
