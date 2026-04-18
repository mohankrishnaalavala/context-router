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
        r
        for r in results
        if isinstance(r, DependencyEdge) and r.edge_type in {"extends", "implements", "tested_by"}
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


# ---------------------------------------------------------------------------
# v3.1 typescript-inheritance-edges: JSX-render + anonymous test-callback
# patterns common in React / bulletproof-react style suites.
# ---------------------------------------------------------------------------


@needs_ts
def test_tested_by_via_jsx_render_in_anonymous_test_callback(tmp_path: Path):
    """A ``*.test.tsx`` file whose ``test('…', () => { render(<Foo />); })``
    body renders an imported component emits ``tested_by`` from Foo →
    synthesized test symbol.  This is the pattern bulletproof-react uses."""
    code = """
import { render, screen } from '@testing-library/react';

import { LoginForm } from '../login-form';

test('should render login form', () => {
    render(<LoginForm />);
    expect(screen.getByRole('button')).toBeInTheDocument();
});
"""
    f = tmp_path / "login-form.test.tsx"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    sources = {e.from_symbol for e in edges}
    assert "LoginForm" in sources, f"expected LoginForm in tested_by sources, got {sources}"
    # The synthesized destination should carry the test label slug.
    dests = [e.to_symbol for e in edges if e.from_symbol == "LoginForm"]
    assert any("render_login_form" in d or d.startswith("test_") for d in dests), dests
    # ``render`` is a test-utility helper — must NOT appear as a SUT.
    assert "render" not in sources


@needs_ts
def test_tested_by_via_named_helper_in_anonymous_test_callback(tmp_path: Path):
    """A test file with ``test('…', () => { createUser(); })`` that
    imports ``createUser`` from a same-repo module emits a ``tested_by``
    edge even though the test callback is an anonymous arrow."""
    code = """
import { createUser } from '../user';

test('creates a user with default team', () => {
    createUser();
});
"""
    f = tmp_path / "user.test.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    sources = {e.from_symbol for e in edges}
    assert "createUser" in sources, f"expected createUser in tested_by sources, got {sources}"


@needs_ts
def test_tested_by_inside_describe_it_nested_block(tmp_path: Path):
    """Nested ``describe(() => { it('…', () => { … }) })`` still establishes
    a test context for the innermost ``it`` callback."""
    code = """
import { useDisclosure } from '../use-disclosure';

describe('useDisclosure', () => {
    it('opens the state', () => {
        useDisclosure();
    });
});
"""
    f = tmp_path / "use-disclosure.test.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    sources = {e.from_symbol for e in edges}
    assert "useDisclosure" in sources, sources


@needs_ts
def test_jsx_render_outside_test_context_emits_no_tested_by(tmp_path: Path):
    """Negative: a non-test TSX file that happens to call ``render(<Foo />)``
    (e.g. a Storybook story, an app entrypoint) does NOT emit tested_by —
    the render must be inside a ``test``/``it``/``describe`` block."""
    code = """
import { render } from 'react-dom';
import { App } from './app';

render(<App />, document.getElementById('root'));
"""
    f = tmp_path / "main.tsx"  # NOT a *.test.tsx file
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    assert edges == [], edges


@needs_ts
def test_render_outside_test_block_in_test_file_emits_no_tested_by(
    tmp_path: Path,
) -> None:
    """Negative within a test file: ``render(<Foo />)`` at module scope
    (outside any ``test(...)`` / ``it(...)``) must NOT emit ``tested_by``.
    The render must be inside a recognised test block."""
    code = """
import { render } from '@testing-library/react';
import { Foo } from '../foo';

// Bare render at module scope — not inside a test(...) callback.
const rendered = render(<Foo />);

test('something', () => {
    expect(1).toBe(1);
});
"""
    f = tmp_path / "weird.test.tsx"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [
        r
        for r in results
        if isinstance(r, DependencyEdge) and r.edge_type == "tested_by" and r.from_symbol == "Foo"
    ]
    assert edges == [], edges


@needs_ts
def test_class_based_inheritance_still_works_after_v31(tmp_path: Path):
    """Regression guard from v3.1 Wave 1: class-based extends/implements
    must remain unchanged — we only *added* function-component paths."""
    code = "class Foo extends Bar implements IX {}\n"
    f = tmp_path / "Foo.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    extends = [
        (e.from_symbol, e.to_symbol)
        for e in results
        if isinstance(e, DependencyEdge) and e.edge_type == "extends"
    ]
    impls = [
        (e.from_symbol, e.to_symbol)
        for e in results
        if isinstance(e, DependencyEdge) and e.edge_type == "implements"
    ]
    assert ("Foo", "Bar") in extends
    assert ("Foo", "IX") in impls


@needs_ts
def test_test_utility_helpers_not_treated_as_sut(tmp_path: Path):
    """``render``, ``renderHook``, ``waitFor``, ``fireEvent`` etc. are test
    infrastructure — they are called inside test blocks but are NEVER the
    system under test.  Importing them must not produce ``tested_by``
    edges pointing at them."""
    code = """
import { render, renderHook, waitFor, fireEvent, screen } from '@testing-library/react';
import { LoginForm } from '../login-form';

test('login form behaves', async () => {
    render(<LoginForm />);
    fireEvent.click(screen.getByRole('button'));
    await waitFor(() => expect(1).toBe(1));
});
"""
    f = tmp_path / "login.test.tsx"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    sources = {e.from_symbol for e in edges}
    # The real SUT must be linked.
    assert "LoginForm" in sources
    # Test-utility identifiers must not be treated as SUTs.
    for util in ("render", "renderHook", "waitFor", "fireEvent", "screen"):
        assert util not in sources, f"{util} should not be treated as SUT ({sources})"


@needs_ts
def test_synthesized_test_symbol_is_registered(tmp_path: Path):
    """The walker registers the synthesized test name as a Symbol so that
    downstream storage/edge resolution can resolve the ``tested_by``
    destination to a real row."""
    code = """
import { useDisclosure } from '../use-disclosure';

test('should open', () => {
    useDisclosure();
});
"""
    f = tmp_path / "use-disclosure.test.ts"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    # At least one function symbol starting with ``test_`` should exist.
    synth = [
        s
        for s in results
        if isinstance(s, Symbol) and s.kind == "function" and s.name.startswith("test_")
    ]
    assert synth, "expected at least one synthesized test symbol"
    # And it must match one end of the tested_by edge.
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    assert any(s.name == e.to_symbol for s in synth for e in edges), (
        "synthesized symbol not linked to a tested_by edge"
    )


@needs_ts
def test_non_test_tsx_with_jsx_emits_no_tested_by(tmp_path: Path):
    """Negative: a plain component TSX that uses JSX but is not a test
    file (and never calls test/it/describe) emits zero ``tested_by``
    edges regardless of its imports."""
    code = """
import { Button } from './button';

export function Toolbar() {
    return <Button label="Save" />;
}
"""
    f = tmp_path / "toolbar.tsx"
    f.write_text(code)
    results = TypeScriptAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    assert edges == [], edges
