"""context-router-language-php: PHP language analyzer plugin.

Extracts functions, methods, classes, and interfaces using tree-sitter.
Registered as the ``php`` analyzer via entry points.
"""
from __future__ import annotations

from pathlib import Path

import tree_sitter_php as tsphp
from tree_sitter import Language, Node, Parser

from contracts.interfaces import DependencyEdge, Symbol

# tree-sitter-php may expose language_php() or language() — check at import
_lang_fn = getattr(tsphp, "language_php", None) or getattr(tsphp, "language", None)
_LANGUAGE = Language(_lang_fn())
_PARSER = Parser(_LANGUAGE)

_SYMBOL_TYPES: dict[str, str] = {
    "function_definition": "function",
    "method_declaration": "method",
    "class_declaration": "class",
    "interface_declaration": "interface",
}


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


class PhpAnalyzer:
    """PHP analyzer — functions, methods, classes, interfaces."""

    def _is_test_file(self, file: Path) -> bool:
        return (
            file.name.endswith("Test.php")
            or "tests" in file.parts
            or "test" in file.parts
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
        kind = _SYMBOL_TYPES.get(node.type)
        if kind:
            name_node = node.child_by_field_name("name")
            if name_node:
                results.append(Symbol(
                    name=_text(name_node),
                    kind=kind,
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="php",
                    signature=f"{kind} {_text(name_node)}",
                ))
        for child in node.children:
            self._walk(child, path, results)
