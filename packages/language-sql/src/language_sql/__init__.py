"""context-router-language-sql: SQL DDL analyzer.

Uses regex on CREATE statements rather than tree-sitter because SQL dialect
fragmentation (PostgreSQL, MySQL, SQLite, T-SQL) makes grammar-based parsing
fragile across real-world codebases. Regex DDL extraction is reliable and
portable. Only TABLE, FUNCTION, PROCEDURE, and VIEW are extracted — INDEX
and TRIGGER are structural metadata, not navigable code symbols.
"""
from __future__ import annotations

import re
from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol

_CREATE_RE = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?(?P<kind>TABLE|VIEW|FUNCTION|PROCEDURE)\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?(?:[\w`\"]+\.)?(?P<name>[\w`\"]+)",
    re.IGNORECASE | re.MULTILINE,
)


class SqlAnalyzer:
    """SQL analyzer — CREATE TABLE/FUNCTION/VIEW/PROCEDURE via regex DDL."""

    def _is_test_file(self, file: Path) -> bool:
        return False  # SQL migration/schema files are never test files

    def analyze(self, path: Path) -> list[Symbol | DependencyEdge]:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        lines = source.splitlines()
        results: list[Symbol | DependencyEdge] = []

        for m in _CREATE_RE.finditer(source):
            kind = m.group("kind").lower()
            name = m.group("name").strip("`\"")
            line_start = source[: m.start()].count("\n") + 1
            next_m = _CREATE_RE.search(source, m.end())
            line_end = (
                source[: next_m.start()].count("\n")
                if next_m
                else len(lines)
            )
            results.append(Symbol(
                name=name,
                kind=kind,
                file=path,
                line_start=line_start,
                line_end=max(line_start, line_end),
                language="sql",
                signature=f"CREATE {kind.upper()} {name}",
            ))

        return results
