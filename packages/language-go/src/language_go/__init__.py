"""context-router-language-go: Go language analyzer plugin.

Extracts functions, methods, and type declarations (structs, interfaces)
using tree-sitter. Registered as the ``go`` analyzer via entry points.
"""
from __future__ import annotations

from pathlib import Path

import tree_sitter_go as tsgo
from tree_sitter import Language, Node, Parser

from contracts.interfaces import DependencyEdge, Symbol

_LANGUAGE = Language(tsgo.language())
_PARSER = Parser(_LANGUAGE)

_BUILTIN_NAMES = frozenset({"init", "main"})


def _text(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


class GoAnalyzer:
    """Go language analyzer — functions, methods, structs, interfaces."""

    def _is_test_file(self, file: Path) -> bool:
        return file.name.endswith("_test.go")

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
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node and _text(name_node) not in _BUILTIN_NAMES:
                results.append(Symbol(
                    name=_text(name_node),
                    kind="function",
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="go",
                    signature=f"func {_text(name_node)}(...)",
                ))

        elif node.type == "method_declaration":
            name_node = node.child_by_field_name("name")
            recv_node = node.child_by_field_name("receiver")
            if name_node:
                recv = _text(recv_node).strip("()") if recv_node else ""
                results.append(Symbol(
                    name=_text(name_node),
                    kind="method",
                    file=path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="go",
                    signature=f"func ({recv}) {_text(name_node)}(...)",
                ))

        elif node.type == "type_declaration":
            for spec in node.children:
                if spec.type == "type_spec":
                    name_node = spec.child_by_field_name("name")
                    type_node = spec.child_by_field_name("type")
                    if name_node and type_node:
                        kind = {
                            "struct_type": "struct",
                            "interface_type": "interface",
                        }.get(type_node.type, "type")
                        results.append(Symbol(
                            name=_text(name_node),
                            kind=kind,
                            file=path,
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                            language="go",
                            signature=f"type {_text(name_node)} {kind}",
                        ))

        for child in node.children:
            self._walk(child, path, results)
