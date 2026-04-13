"""Tests for the language-typescript package."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.interfaces import DependencyEdge, LanguageAnalyzer, Symbol
from language_typescript import TypeScriptAnalyzer

try:
    import tree_sitter_typescript  # noqa: F401

    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False

needs_ts = pytest.mark.skipif(not HAS_TREE_SITTER, reason="tree-sitter-typescript not installed")


def test_import():
    import language_typescript  # noqa: F401


def test_implements_protocol():
    instance = TypeScriptAnalyzer()
    assert isinstance(instance, LanguageAnalyzer)


def test_returns_list_on_missing_file():
    instance = TypeScriptAnalyzer()
    result = instance.analyze(Path("/nonexistent/file.ts"))
    assert isinstance(result, list)


@needs_ts
def test_extracts_function(tmp_path: Path):
    code = "function greet(name: string): string { return name; }\n"
    f = tmp_path / "sample.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    symbols = [r for r in results if isinstance(r, Symbol) and r.kind == "function"]
    assert any(s.name == "greet" for s in symbols)


@needs_ts
def test_extracts_class(tmp_path: Path):
    code = "class Greeter { greet() { return 'hi'; } }\n"
    f = tmp_path / "sample.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    symbols = [r for r in results if isinstance(r, Symbol) and r.kind == "class"]
    assert any(s.name == "Greeter" for s in symbols)


@needs_ts
def test_extracts_interface(tmp_path: Path):
    code = "interface IUser { name: string; age: number; }\n"
    f = tmp_path / "sample.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    symbols = [r for r in results if isinstance(r, Symbol) and r.kind == "interface"]
    assert any(s.name == "IUser" for s in symbols)


@needs_ts
def test_extracts_import_edge(tmp_path: Path):
    code = "import { readFile } from 'fs';\nimport path from 'path';\n"
    f = tmp_path / "sample.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "imports"]
    modules = {e.to_symbol for e in edges}
    assert "fs" in modules
    assert "path" in modules


@needs_ts
def test_extracts_calls_edge(tmp_path: Path):
    code = """
function alpha(): void {
    beta();
}

function beta(): void {}
"""
    f = tmp_path / "sample.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    calls = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    froms = {e.from_symbol for e in calls}
    tos = {e.to_symbol for e in calls}
    assert "alpha" in froms
    assert "beta" in tos


@needs_ts
def test_tsx_file_parses(tmp_path: Path):
    code = "function App(): JSX.Element { return <div />; }\n"
    f = tmp_path / "App.tsx"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    # Should not raise; symbols may or may not be extracted depending on grammar
    assert isinstance(results, list)


@needs_ts
def test_language_is_typescript(tmp_path: Path):
    code = "function hello() {}\n"
    f = tmp_path / "x.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    symbols = [r for r in results if isinstance(r, Symbol)]
    assert all(s.language == "typescript" for s in symbols)
