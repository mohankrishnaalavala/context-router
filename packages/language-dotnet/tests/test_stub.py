"""Tests for language_dotnet.DotnetAnalyzer."""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, LanguageAnalyzer, Symbol
from language_dotnet import DotnetAnalyzer

SAMPLE_CS = """\
using System;
using System.Collections.Generic;

namespace MyApp.Services
{
    public class UserService
    {
        private string _name;

        public string GetName()
        {
            return _name;
        }

        public void SetName(string name)
        {
            _name = name;
        }
    }
}
"""

SAMPLE_CS_INTERFACE = """\
using System;

namespace MyApp.Contracts
{
    public interface IUserService
    {
        string GetName();
    }
}
"""


def test_import():
    import language_dotnet  # noqa: F401


def test_implements_protocol():
    assert isinstance(DotnetAnalyzer(), LanguageAnalyzer)


def test_returns_list(tmp_path: Path):
    result = DotnetAnalyzer().analyze(tmp_path / "nonexistent.cs")
    assert isinstance(result, list)


def test_extracts_namespace(tmp_path: Path):
    f = tmp_path / "UserService.cs"
    f.write_text(SAMPLE_CS)
    results = DotnetAnalyzer().analyze(f)

    namespaces = [s for s in results if isinstance(s, Symbol) and s.kind == "namespace"]
    names = {s.name for s in namespaces}
    assert "MyApp.Services" in names


def test_extracts_class(tmp_path: Path):
    f = tmp_path / "UserService.cs"
    f.write_text(SAMPLE_CS)
    results = DotnetAnalyzer().analyze(f)

    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    names = {s.name for s in classes}
    assert "UserService" in names


def test_extracts_methods(tmp_path: Path):
    f = tmp_path / "UserService.cs"
    f.write_text(SAMPLE_CS)
    results = DotnetAnalyzer().analyze(f)

    methods = [s for s in results if isinstance(s, Symbol) and s.kind == "method"]
    names = {s.name for s in methods}
    assert "GetName" in names
    assert "SetName" in names


def test_extracts_using_directives_as_edges(tmp_path: Path):
    f = tmp_path / "UserService.cs"
    f.write_text(SAMPLE_CS)
    results = DotnetAnalyzer().analyze(f)

    import_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "imports"]
    assert len(import_edges) >= 1
    to_symbols = {e.to_symbol for e in import_edges}
    # System.Collections.Generic → leaf "Generic"
    assert "System" in to_symbols or "Generic" in to_symbols


def test_extracts_interface(tmp_path: Path):
    f = tmp_path / "IUserService.cs"
    f.write_text(SAMPLE_CS_INTERFACE)
    results = DotnetAnalyzer().analyze(f)

    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    names = {s.name for s in classes}
    assert "IUserService" in names


def test_line_numbers_set(tmp_path: Path):
    f = tmp_path / "UserService.cs"
    f.write_text(SAMPLE_CS)
    results = DotnetAnalyzer().analyze(f)

    for s in results:
        if isinstance(s, Symbol) and s.kind in ("class", "method", "namespace"):
            assert s.line_start > 0, f"{s.name} has no line_start"


def test_empty_file(tmp_path: Path):
    f = tmp_path / "Empty.cs"
    f.write_text("")
    results = DotnetAnalyzer().analyze(f)
    assert results == []


def test_invalid_path_returns_empty():
    results = DotnetAnalyzer().analyze(Path("/nonexistent/File.cs"))
    assert results == []


SAMPLE_CS_WITH_CALLS = """\
using System;

namespace MyApp.Services
{
    public class OrderService
    {
        private UserService _userService;

        public void ProcessOrder(string userId)
        {
            ValidateUser(userId);
            BuildOrder(userId);
        }

        private void ValidateUser(string id)
        {
        }

        private void BuildOrder(string id)
        {
        }
    }
}
"""

SAMPLE_CS_WITH_PROPERTY = """\
namespace MyApp
{
    public class Config
    {
        public string Host { get; set; }
        public int Port { get; set; }
    }
}
"""


def test_call_edges(tmp_path: Path):
    f = tmp_path / "OrderService.cs"
    f.write_text(SAMPLE_CS_WITH_CALLS)
    results = DotnetAnalyzer().analyze(f)

    call_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    callee_names = {e.to_symbol for e in call_edges}
    assert "ValidateUser" in callee_names
    assert "BuildOrder" in callee_names


def test_call_edges_have_method_as_source(tmp_path: Path):
    f = tmp_path / "OrderService.cs"
    f.write_text(SAMPLE_CS_WITH_CALLS)
    results = DotnetAnalyzer().analyze(f)

    call_edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    sources = {e.from_symbol for e in call_edges}
    assert "ProcessOrder" in sources


def test_property_extraction(tmp_path: Path):
    f = tmp_path / "Config.cs"
    f.write_text(SAMPLE_CS_WITH_PROPERTY)
    results = DotnetAnalyzer().analyze(f)

    props = [s for s in results if isinstance(s, Symbol) and s.kind == "property"]
    names = {s.name for s in props}
    assert "Host" in names
    assert "Port" in names
