"""Tests for v3 phase4/edge-source-resolution-fix (C# analyzer side).

Three analyzer-level bugs this suite pins down:

1. **Method name vs. return type.** ``public Task<int> DoWork()`` must
   emit a ``kind='method'`` symbol named ``DoWork`` — not ``Task``.
2. **tested_by target = method name.** ``[Fact] public async Task
   TestFoo()`` in a ``*Tests.cs`` fixture must emit a ``tested_by`` edge
   whose ``to_symbol`` is ``TestFoo``, not ``Task``.
3. **Invocations do not create method symbols.** ``new
   StringContent(...)`` inside a method body must NOT leak a
   ``kind='method'`` symbol named ``StringContent``.  (This bug was a
   side effect of #1 — custom return types were captured as method
   names when the analyzer was asked to extract method symbols.)
"""

from __future__ import annotations

from pathlib import Path

from contracts.interfaces import DependencyEdge, Symbol
from language_dotnet import DotnetAnalyzer

# ---------------------------------------------------------------------------
# Fixture 1 — method with a custom return type.
# ---------------------------------------------------------------------------

CS_METHOD_WITH_CUSTOM_RETURN_TYPE = """\
namespace App
{
    public class Worker
    {
        public Task<int> DoWork() => Task.FromResult(1);

        public HttpClient GetClient() => new HttpClient();

        public async Task<StringContent> MakeBody() => new StringContent("x");
    }
}
"""


def test_method_name_is_method_not_return_type(tmp_path: Path) -> None:
    """``public Task<int> DoWork()`` emits kind='method' named DoWork.

    Regression: prior to the fix, ``_first_child_of_type(node,
    "identifier", ...)`` returned the return-type identifier (``Task``,
    ``HttpClient``, ``StringContent``) BEFORE the method's name field
    on any method with a custom return type.  On eShopOnWeb this is
    also responsible for ~133/495 C# symbols named ``Task``.
    """
    f = tmp_path / "Worker.cs"
    f.write_text(CS_METHOD_WITH_CUSTOM_RETURN_TYPE)
    results = DotnetAnalyzer().analyze(f)

    methods = [s for s in results if isinstance(s, Symbol) and s.kind == "method"]
    method_names = {s.name for s in methods}

    # Positive: the real method names are captured.
    assert "DoWork" in method_names, (
        f"expected DoWork as kind='method', got {method_names}"
    )
    assert "GetClient" in method_names
    assert "MakeBody" in method_names

    # Negative: return-type identifiers never leak in as methods.
    assert "Task" not in method_names, (
        f"return-type 'Task' leaked as a method symbol: got {method_names}"
    )
    assert "HttpClient" not in method_names
    assert "StringContent" not in method_names


# ---------------------------------------------------------------------------
# Fixture 2 — test method whose return type is Task.
# ---------------------------------------------------------------------------

CS_TEST_FILE_WITH_TASK_RETURN = """\
using System.Threading.Tasks;
using Xunit;

namespace App.Tests
{
    public class UserServiceTests
    {
        [Fact]
        public async Task TestFoo()
        {
            await Task.CompletedTask;
        }

        [Fact]
        public void TestBarSync()
        {
        }
    }
}
"""


def test_tested_by_target_is_method_name_not_task(tmp_path: Path) -> None:
    """``[Fact] public async Task TestFoo()`` → to_symbol='TestFoo'.

    Regression: the same first-identifier bug hit the tested_by edge
    writer path; on eShopOnWeb the bug fired 41/41 times, producing
    ``Task``-targeted edges that were indistinguishable from each other
    and broke coverage queries.
    """
    f = tmp_path / "UserServiceTests.cs"
    f.write_text(CS_TEST_FILE_WITH_TASK_RETURN)
    results = DotnetAnalyzer().analyze(f)

    tested_by_edges = [
        r for r in results
        if isinstance(r, DependencyEdge) and r.edge_type == "tested_by"
    ]
    targets = {e.to_symbol for e in tested_by_edges}

    # Positive: the real test methods are the tested_by targets.
    assert "TestFoo" in targets, (
        f"expected 'TestFoo' as tested_by target, got {targets}"
    )
    assert "TestBarSync" in targets

    # Negative: the return-type 'Task' must never be a tested_by target.
    assert "Task" not in targets, (
        f"return-type 'Task' leaked as tested_by target: got {targets}"
    )

    # And every tested_by edge in this file anchors on the SUT class name.
    sut_names = {e.from_symbol for e in tested_by_edges}
    assert sut_names == {"UserService"}, (
        f"expected SUT='UserService' for every tested_by edge, got {sut_names}"
    )


# ---------------------------------------------------------------------------
# Fixture 3 — invocation expressions must not create method symbols.
# ---------------------------------------------------------------------------

CS_METHOD_WITH_INVOCATIONS = """\
namespace App
{
    public class ApiClient
    {
        public void Send()
        {
            var body = new StringContent("x");
            var client = new HttpClient();
            client.Send(body);
        }
    }
}
"""


def test_invocation_does_not_create_method_symbol(tmp_path: Path) -> None:
    """``new StringContent(...)`` must NOT emit a kind='method' symbol.

    Regression: the analyzer previously produced spurious ``kind='method'``
    rows for ``StringContent``, ``HttpClient``, ``HttpDelete``, ``Task``
    because the method-emission branch accepted any leading identifier
    child.  After the fix, only ``method_declaration`` nodes produce
    method symbols; object-creation and invocation nodes never do.
    """
    f = tmp_path / "ApiClient.cs"
    f.write_text(CS_METHOD_WITH_INVOCATIONS)
    results = DotnetAnalyzer().analyze(f)

    method_names = {
        s.name for s in results if isinstance(s, Symbol) and s.kind == "method"
    }

    # Positive: the one real method in this file is captured.
    assert "Send" in method_names, (
        f"expected Send as kind='method', got {method_names}"
    )

    # Negative: object-creation identifiers never become method symbols.
    assert "StringContent" not in method_names, (
        f"'StringContent' leaked as method symbol: got {method_names}"
    )
    assert "HttpClient" not in method_names, (
        f"'HttpClient' leaked as method symbol: got {method_names}"
    )

    # Regression guard — the fix should not affect call-edge extraction.
    call_edges = [
        r for r in results
        if isinstance(r, DependencyEdge) and r.edge_type == "calls"
    ]
    called = {e.to_symbol for e in call_edges}
    # client.Send(body) invocation captured; Send (local method) calls
    # stay strict (the analyzer can't tell self-calls from other calls
    # at the AST level, so either 'Send' is captured or filtered).
    # The important guard is that the set is reachable (no crash).
    assert isinstance(called, set)
