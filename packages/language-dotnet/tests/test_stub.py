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


SAMPLE_CS_CTOR = """\
using Microsoft.AspNetCore.Mvc;

namespace Example.Api;

[ApiController]
[Route("api/[controller]")]
public class UsersController : ControllerBase
{
    private readonly IUserService _svc;

    public UsersController(IUserService svc)
    {
        _svc = svc;
    }

    [HttpGet("{id}")]
    public IActionResult FindOne(long id)
    {
        return Ok(_svc.Find(id));
    }
}
"""


def test_extracts_constructor_declaration(tmp_path: Path):
    f = tmp_path / "UsersController.cs"
    f.write_text(SAMPLE_CS_CTOR)
    results = DotnetAnalyzer().analyze(f)
    ctors = [s for s in results if isinstance(s, Symbol) and s.kind == "constructor"]
    assert any(s.name == "UsersController" for s in ctors)


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
    """Interfaces must be labeled kind='interface' (was kind='class' pre-v3)."""
    f = tmp_path / "IUserService.cs"
    f.write_text(SAMPLE_CS_INTERFACE)
    results = DotnetAnalyzer().analyze(f)

    interfaces = [s for s in results if isinstance(s, Symbol) and s.kind == "interface"]
    names = {s.name for s in interfaces}
    assert "IUserService" in names, (
        f"expected IUserService with kind='interface', got kinds="
        f"{[(s.name, s.kind) for s in results if isinstance(s, Symbol)]}"
    )
    # Negative: the interface must not leak out as kind='class' anymore.
    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    assert "IUserService" not in {s.name for s in classes}


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


# ---------------------------------------------------------------------------
# v3 phase1/interface-kind-label: kind correctness across type declarations.
# ---------------------------------------------------------------------------

SAMPLE_CS_ALL_KINDS = """\
namespace MyApp.Domain
{
    public class Person { }

    public interface IGreeter
    {
        string Greet();
    }

    public record PersonRecord(string Name, int Age);

    public struct Point
    {
        public int X;
        public int Y;
    }
}
"""


def test_kind_labels_class_interface_record_struct(tmp_path: Path):
    """Each C# type-declaration node-type must map to its matching kind."""
    f = tmp_path / "AllKinds.cs"
    f.write_text(SAMPLE_CS_ALL_KINDS)
    results = DotnetAnalyzer().analyze(f)

    by_name = {
        s.name: s.kind
        for s in results
        if isinstance(s, Symbol) and s.kind in {"class", "interface", "record", "struct"}
    }
    assert by_name.get("Person") == "class"
    assert by_name.get("IGreeter") == "interface"
    assert by_name.get("PersonRecord") == "record"
    assert by_name.get("Point") == "struct"


def test_plain_class_regression_still_kind_class(tmp_path: Path):
    """Regression: a plain class in isolation stays kind='class' (unchanged)."""
    f = tmp_path / "UserService.cs"
    f.write_text(SAMPLE_CS)  # Only contains a plain class.
    results = DotnetAnalyzer().analyze(f)

    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    assert {s.name for s in classes} == {"UserService"}
    # No spurious non-class kinds leak out from a plain-class file.
    leaked = [
        s for s in results
        if isinstance(s, Symbol) and s.kind in {"interface", "record", "struct"}
    ]
    assert leaked == []


# ---------------------------------------------------------------------------
# v3 phase3/enum-symbols-extracted: C# enums must emit kind='enum'.
# ---------------------------------------------------------------------------

SAMPLE_CS_ENUM = """\
namespace MyApp.Models
{
    public enum Priority { Low, Medium, High }

    public class Task
    {
        public string Title { get; set; }
        public Priority Level { get; set; }
    }
}
"""


def test_extracts_enum_declaration(tmp_path: Path):
    """C# enums must be labeled kind='enum' (Phase 3 outcome)."""
    f = tmp_path / "Priority.cs"
    f.write_text(SAMPLE_CS_ENUM)
    results = DotnetAnalyzer().analyze(f)

    enums = [s for s in results if isinstance(s, Symbol) and s.kind == "enum"]
    names = {s.name for s in enums}
    assert "Priority" in names, (
        f"expected Priority with kind='enum', got kinds="
        f"{[(s.name, s.kind) for s in results if isinstance(s, Symbol)]}"
    )
    # Negative: the enum must not leak out as kind='class'.
    classes = [s for s in results if isinstance(s, Symbol) and s.kind == "class"]
    assert "Priority" not in {s.name for s in classes}
    # The sibling class must still be kind='class' (non-enum types unaffected).
    assert "Task" in {s.name for s in classes}


def test_enum_only_file_emits_single_enum_symbol(tmp_path: Path):
    """Regression: a file with just an enum produces one kind='enum' symbol."""
    f = tmp_path / "Color.cs"
    f.write_text("public enum Color { Red, Green, Blue }\n")
    results = DotnetAnalyzer().analyze(f)
    kinds = [s.kind for s in results if isinstance(s, Symbol) and s.name == "Color"]
    assert kinds == ["enum"], f"expected ['enum'], got {kinds}"


# ---------------------------------------------------------------------------
# v3 phase3/edge-kinds-extended: extends / implements / tested_by edges.
# ---------------------------------------------------------------------------

SAMPLE_CS_INHERITANCE = """\
namespace App
{
    public class Dog : Animal, ITrainable, IFeedable
    {
        public void Bark() { }
    }

    public interface IRepo : IService, IWritable { }

    public record Rec(string Name) : BaseRec, IRec;

    public class Orphan : IStandalone { }
}
"""


def test_extends_edge_from_class(tmp_path: Path):
    f = tmp_path / "Dog.cs"
    f.write_text(SAMPLE_CS_INHERITANCE)
    results = DotnetAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "extends"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("Dog", "Animal") in pairs, f"expected Dog->Animal extends, got {pairs}"
    assert ("Rec", "BaseRec") in pairs, f"expected Rec->BaseRec extends, got {pairs}"


def test_implements_edges_from_class_and_record(tmp_path: Path):
    f = tmp_path / "Dog.cs"
    f.write_text(SAMPLE_CS_INHERITANCE)
    results = DotnetAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "implements"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("Dog", "ITrainable") in pairs
    assert ("Dog", "IFeedable") in pairs
    assert ("Rec", "IRec") in pairs
    # Orphan : IStandalone → no base class (all start with I), so just implements.
    assert ("Orphan", "IStandalone") in pairs


def test_interface_extends_yields_extends_edges(tmp_path: Path):
    f = tmp_path / "IRepo.cs"
    f.write_text(SAMPLE_CS_INHERITANCE)
    results = DotnetAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "extends"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("IRepo", "IService") in pairs
    assert ("IRepo", "IWritable") in pairs


SAMPLE_CS_TEST = """\
namespace App.Tests
{
    public class UserServiceTests
    {
        [Fact]
        public void FindOne_WithValidId_ReturnsUser() { }

        [Theory]
        public void FindAll_WithFilters_ReturnsMatches() { }

        [SetUp]
        public void Setup() { }
    }
}
"""


def test_tested_by_edges_in_test_file(tmp_path: Path):
    """A C# test file ``FooTests.cs`` emits tested_by edges from ``Foo``
    (the inferred SUT) to each method with a test attribute."""
    f = tmp_path / "UserServiceTests.cs"
    f.write_text(SAMPLE_CS_TEST)
    results = DotnetAnalyzer().analyze(f)
    edges = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"]
    pairs = {(e.from_symbol, e.to_symbol) for e in edges}
    assert ("UserService", "FindOne_WithValidId_ReturnsUser") in pairs
    assert ("UserService", "FindAll_WithFilters_ReturnsMatches") in pairs
    # [SetUp] is not a test attribute — no tested_by for Setup.
    assert ("UserService", "Setup") not in pairs


def test_no_inheritance_or_tested_by_in_plain_class(tmp_path: Path):
    """Negative: a plain class with no base list yields zero spec edges."""
    f = tmp_path / "UserService.cs"
    f.write_text(SAMPLE_CS)
    results = DotnetAnalyzer().analyze(f)
    spec_edges = [
        r for r in results
        if isinstance(r, DependencyEdge)
        and r.edge_type in {"extends", "implements", "tested_by"}
    ]
    assert spec_edges == []


def test_calls_and_imports_unchanged_after_v3(tmp_path: Path):
    """Regression: ``calls`` and ``imports`` emission is unchanged."""
    f = tmp_path / "OrderService.cs"
    f.write_text(SAMPLE_CS_WITH_CALLS)
    results = DotnetAnalyzer().analyze(f)
    calls = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "calls"]
    imports = [r for r in results if isinstance(r, DependencyEdge) and r.edge_type == "imports"]
    # ValidateUser + BuildOrder = 2 method calls captured.
    assert len(calls) >= 2
    # using System; → 1 import edge.
    assert len(imports) >= 1
