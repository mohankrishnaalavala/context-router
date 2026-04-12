"""Tests for language_python.PythonAnalyzer."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, LanguageAnalyzer, Symbol
from language_python import PythonAnalyzer

SAMPLE_PY = '''\
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"


class Greeter:
    def greet(self, name: str) -> str:
        return hello(name)


import os
from pathlib import Path
'''


def test_import():
    import language_python  # noqa: F401


def test_implements_protocol():
    assert isinstance(PythonAnalyzer(), LanguageAnalyzer)


def test_returns_list(tmp_path: Path):
    result = PythonAnalyzer().analyze(tmp_path / "nonexistent.py")
    assert isinstance(result, list)


def test_extracts_function(tmp_path: Path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    results = PythonAnalyzer().analyze(f)

    funcs = [s for s in results if isinstance(s, Symbol) and s.kind == "function"]
    names = {s.name for s in funcs}
    assert "hello" in names


def test_extracts_class(tmp_path: Path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    results = PythonAnalyzer().analyze(f)

    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    names = {s.name for s in classes}
    assert "Greeter" in names


def test_extracts_method(tmp_path: Path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    results = PythonAnalyzer().analyze(f)

    funcs = [s for s in results if isinstance(s, Symbol) and s.kind == "function"]
    names = {s.name for s in funcs}
    assert "greet" in names


def test_extracts_imports_as_edges(tmp_path: Path):
    """Imports are now emitted as DependencyEdge, not as Symbol(kind='import')."""
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    results = PythonAnalyzer().analyze(f)

    # No import symbols should exist
    import_syms = [s for s in results if isinstance(s, Symbol) and s.kind == "import"]
    assert import_syms == [], "import symbols should no longer be emitted"

    # Edges for the imports should be present
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "imports"]
    to_symbols = {e.to_symbol for e in edges}
    assert "os" in to_symbols
    # from pathlib import Path → imported name is "Path"
    assert "Path" in to_symbols


def test_extracts_docstring(tmp_path: Path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    results = PythonAnalyzer().analyze(f)

    hello_syms = [s for s in results if isinstance(s, Symbol) and s.name == "hello"]
    assert hello_syms
    assert "Say hello" in hello_syms[0].docstring


def test_line_numbers_set(tmp_path: Path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_PY)
    results = PythonAnalyzer().analyze(f)

    symbols = [s for s in results if isinstance(s, Symbol)]
    for sym in symbols:
        if sym.kind in ("function", "class"):
            assert sym.line_start > 0, f"{sym.name} has no line_start"


def test_empty_file(tmp_path: Path):
    f = tmp_path / "empty.py"
    f.write_text("")
    results = PythonAnalyzer().analyze(f)
    assert results == []


def test_invalid_path_returns_empty():
    results = PythonAnalyzer().analyze(Path("/nonexistent/file.py"))
    assert results == []
