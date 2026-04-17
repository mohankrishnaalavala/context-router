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
def test_extracts_enum_declaration(tmp_path: Path):
    code = "export enum Status { Active, Inactive, Suspended }\n"
    f = tmp_path / "enum.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    enums = [s for s in results if getattr(s, "kind", None) == "enum"]
    assert any(s.name == "Status" for s in enums)


@needs_ts
def test_extracts_const_enum_declaration(tmp_path: Path):
    code = "const enum Mode { Read = 1, Write = 2 }\n"
    f = tmp_path / "const_enum.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    enums = [s for s in results if getattr(s, "kind", None) == "enum"]
    assert any(s.name == "Mode" for s in enums)


@needs_ts
def test_extracts_decorators_on_class_signature(tmp_path: Path):
    code = (
        "@Component({selector: 'app-foo', templateUrl: './foo.html'})\n"
        "@Injectable()\n"
        "export class FooComponent {\n"
        "  doStuff() { return 1; }\n"
        "}\n"
    )
    f = tmp_path / "foo.component.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    classes = [s for s in results if getattr(s, "kind", None) == "class"]
    foo = next((s for s in classes if s.name == "FooComponent"), None)
    assert foo is not None
    assert "@Component" in foo.signature
    assert "@Injectable" in foo.signature


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


# ---------------------------------------------------------------------------
# v3 phase3/edge-kinds-extended: extends / implements / tested_by edges.
# ---------------------------------------------------------------------------

TS_INHERITANCE = """\
class Foo extends Base implements IFoo, IBar {}
interface IRepo extends IService, IWritable {}
class Bar extends other.module.Base {}
class Solo {}
"""


@needs_ts
def test_extends_and_implements_from_class(tmp_path: Path):
    """``class Foo extends Base implements IFoo, IBar`` emits exactly one
    extends edge and one implements edge per interface."""
    f = tmp_path / "Foo.ts"
    f.write_text(TS_INHERITANCE)
    results = TypeScriptAnalyzer().analyze(f)
    extends = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "extends"]
    impls = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "implements"]
    ext_pairs = {(e.from_symbol, e.to_symbol) for e in extends}
    imp_pairs = {(e.from_symbol, e.to_symbol) for e in impls}
    assert ("Foo", "Base") in ext_pairs
    assert ("Foo", "IFoo") in imp_pairs
    assert ("Foo", "IBar") in imp_pairs
    # Dotted base → leaf identifier
    assert ("Bar", "Base") in ext_pairs
    # Solo has no heritage → no edges
    assert all(src != "Solo" for src, _ in ext_pairs | imp_pairs)


@needs_ts
def test_interface_extends_multiple_super_interfaces(tmp_path: Path):
    f = tmp_path / "IRepo.ts"
    f.write_text(TS_INHERITANCE)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "extends"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("IRepo", "IService") in pairs
    assert ("IRepo", "IWritable") in pairs


@needs_ts
def test_tested_by_for_named_test_function(tmp_path: Path):
    """A ``.test.ts`` file with a named test function calling an imported
    source symbol emits a tested_by edge from the import → the test fn."""
    code = """
import { add, multiply } from './math';

function testAdd() {
    return add(1, 2);
}

function testMultiply() {
    return multiply(3, 4);
}
"""
    f = tmp_path / "math.test.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("add", "testAdd") in pairs
    assert ("multiply", "testMultiply") in pairs


@needs_ts
def test_no_spec_edges_in_plain_source(tmp_path: Path):
    """Negative: plain source (no heritage, no tests) emits zero of the
    v3-phase3 edge kinds."""
    code = """
function plain() { return 1; }
class Standalone { value = 42; }
"""
    f = tmp_path / "plain.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    spec_edges = [
        r for r in results
        if isinstance(r, DependencyEdge)
        and r.edge_type in {"extends", "implements", "tested_by"}
    ]
    assert spec_edges == []


@needs_ts
def test_calls_and_imports_unchanged_after_v3(tmp_path: Path):
    """Regression: existing calls/imports emission is unchanged."""
    code = """
import { helper } from 'lib';

function alpha() {
    beta();
}

function beta() { return helper(); }
"""
    f = tmp_path / "sample.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    calls = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    imports = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "imports"]
    assert any(e.from_symbol == "alpha" and e.to_symbol == "beta" for e in calls)
    assert any(e.to_symbol == "lib" for e in imports)
