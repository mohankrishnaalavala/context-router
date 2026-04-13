"""Tests for language_java.JavaAnalyzer."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, LanguageAnalyzer, Symbol
from language_java import JavaAnalyzer

SAMPLE_JAVA = """\
package com.example;

import java.util.List;
import java.util.Map;

public class UserService {
    private String name;

    public String getName() {
        return this.name;
    }

    public void setName(String name) {
        this.name = name;
    }
}
"""


def test_import():
    import language_java  # noqa: F401


def test_implements_protocol():
    assert isinstance(JavaAnalyzer(), LanguageAnalyzer)


def test_returns_list(tmp_path: Path):
    result = JavaAnalyzer().analyze(tmp_path / "nonexistent.java")
    assert isinstance(result, list)


def test_extracts_class(tmp_path: Path):
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)

    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    names = {s.name for s in classes}
    assert "UserService" in names


def test_extracts_methods(tmp_path: Path):
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)

    methods = [s for s in results if isinstance(s, Symbol) and s.kind == "method"]
    names = {s.name for s in methods}
    assert "getName" in names
    assert "setName" in names


def test_extracts_imports_as_edges(tmp_path: Path):
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)

    import_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "imports"]
    assert len(import_edges) >= 1
    to_symbols = {e.to_symbol for e in import_edges}
    # java.util.List → leaf "List"
    assert "List" in to_symbols


def test_line_numbers_set(tmp_path: Path):
    f = tmp_path / "UserService.java"
    f.write_text(SAMPLE_JAVA)
    results = JavaAnalyzer().analyze(f)

    for s in results:
        if isinstance(s, Symbol) and s.kind in ("class", "method"):
            assert s.line_start > 0, f"{s.name} has no line_start"


def test_empty_file(tmp_path: Path):
    f = tmp_path / "Empty.java"
    f.write_text("")
    results = JavaAnalyzer().analyze(f)
    assert results == []


def test_invalid_path_returns_empty():
    results = JavaAnalyzer().analyze(Path("/nonexistent/File.java"))
    assert results == []


SAMPLE_JAVA_WITH_CALLS = """\
package com.example;

public class OrderService {
    private UserService userService;

    public void processOrder(String userId) {
        validateUser(userId);
        buildOrder(userId);
    }

    private void validateUser(String id) {
        userService.checkPermissions(id);
    }

    private void buildOrder(String id) {
    }
}
"""


def test_call_edges(tmp_path: Path):
    f = tmp_path / "OrderService.java"
    f.write_text(SAMPLE_JAVA_WITH_CALLS)
    results = JavaAnalyzer().analyze(f)

    call_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    callee_names = {e.to_symbol for e in call_edges}
    assert "validateUser" in callee_names
    assert "buildOrder" in callee_names


def test_call_edges_have_method_as_source(tmp_path: Path):
    f = tmp_path / "OrderService.java"
    f.write_text(SAMPLE_JAVA_WITH_CALLS)
    results = JavaAnalyzer().analyze(f)

    call_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    sources = {e.from_symbol for e in call_edges}
    # Call edges originate from method names, not file paths
    assert "processOrder" in sources
