"""context-router-language-rust: Rust language analyzer plugin.

Extracts functions, impl methods, structs, enums, and traits using
tree-sitter. Registered as the ``rs`` analyzer via entry points.
"""
from __future__ import annotations

from pathlib import Path

import tree_sitter_rust as tsrust
from tree_sitter import Language, Node, Parser

from contracts.interfaces import DependencyEdge, Symbol

_LANGUAGE = Language(tsrust.language())
_PARSER = Parser(_LANGUAGE)


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


class RustAnalyzer:
    """Rust analyzer — functions, impl methods, structs, enums, traits."""

    def _is_test_file(self, file: Path) -> bool:
        return "tests" in file.parts or "test" in file.parts

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        try:
            source = path.read_bytes()
        except OSError:
            return []
        tree = _PARSER.parse(source)
        results: list[Symbol | DependencyEdge] = []
        self._walk(tree.root_node, path, results, impl_name=None)
        return results

    def _walk(
        self, node: Node, path: Path, results: list, impl_name: str | None
    ) -> None:
        if node.type == "function_item":
            name_node = node.child_by_field_name("name")
            if name_node:
                kind = "method" if impl_name else "function"
                results.append(Symbol(
                    name=_text(name_node),
                    kind=kind,
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="rs",
                    signature=f"fn {_text(name_node)}(...)",
                ))

        elif node.type == "impl_item":
            type_node = node.child_by_field_name("type")
            impl_type = _text(type_node) if type_node else "impl"
            for child in node.children:
                self._walk(child, path, results, impl_name=impl_type)
            return  # children already walked

        elif node.type in ("struct_item", "enum_item", "trait_item"):
            name_node = node.child_by_field_name("name")
            kind = node.type.replace("_item", "")
            if name_node:
                results.append(Symbol(
                    name=_text(name_node),
                    kind=kind,
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="rs",
                    signature=f"{kind} {_text(name_node)}",
                ))

        for child in node.children:
            self._walk(child, path, results, impl_name=impl_name)
