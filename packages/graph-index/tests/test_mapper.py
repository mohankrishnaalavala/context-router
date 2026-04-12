"""Tests for graph_index.test_mapper.TestFileMapper."""

from __future__ import annotations

from pathlib import Path

from graph_index.test_mapper import TestFileMapper


def test_pytest_prefix_convention() -> None:
    """test_foo.py maps to foo.py (pytest prefix convention)."""
    mapper = TestFileMapper()
    source = [Path("src/auth.py")]
    tests = [Path("tests/test_auth.py")]

    result = mapper.map(source, tests)
    assert result[Path("src/auth.py")] == [Path("tests/test_auth.py")]


def test_pytest_suffix_convention() -> None:
    """foo_test.py maps to foo.py (pytest suffix convention)."""
    mapper = TestFileMapper()
    source = [Path("src/auth.py")]
    tests = [Path("tests/auth_test.py")]

    result = mapper.map(source, tests)
    assert result[Path("src/auth.py")] == [Path("tests/auth_test.py")]


def test_junit_test_suffix_convention() -> None:
    """FooTest.java maps to Foo.java (JUnit convention)."""
    mapper = TestFileMapper()
    source = [Path("src/UserService.java")]
    tests = [Path("tests/UserServiceTest.java")]

    result = mapper.map(source, tests)
    assert result[Path("src/UserService.java")] == [Path("tests/UserServiceTest.java")]


def test_junit_tests_suffix_convention() -> None:
    """FooTests.java maps to Foo.java (JUnit plural convention)."""
    mapper = TestFileMapper()
    source = [Path("src/UserService.java")]
    tests = [Path("tests/UserServiceTests.java")]

    result = mapper.map(source, tests)
    assert result[Path("src/UserService.java")] == [Path("tests/UserServiceTests.java")]


def test_xunit_tests_suffix_convention() -> None:
    """FooTests.cs maps to Foo.cs (xUnit convention)."""
    mapper = TestFileMapper()
    source = [Path("src/AuthService.cs")]
    tests = [Path("tests/AuthServiceTests.cs")]

    result = mapper.map(source, tests)
    assert result[Path("src/AuthService.cs")] == [Path("tests/AuthServiceTests.cs")]


def test_xunit_test_suffix_convention() -> None:
    """FooTest.cs maps to Foo.cs (xUnit single convention)."""
    mapper = TestFileMapper()
    source = [Path("src/AuthService.cs")]
    tests = [Path("tests/AuthServiceTest.cs")]

    result = mapper.map(source, tests)
    assert result[Path("src/AuthService.cs")] == [Path("tests/AuthServiceTest.cs")]


def test_unmatched_source_returns_empty_list() -> None:
    """Source files with no matching test files map to empty list."""
    mapper = TestFileMapper()
    source = [Path("src/utils.py")]
    tests = [Path("tests/test_auth.py")]

    result = mapper.map(source, tests)
    assert result[Path("src/utils.py")] == []


def test_all_sources_get_entry() -> None:
    """Every source file gets an entry in the result dict."""
    mapper = TestFileMapper()
    sources = [Path("src/a.py"), Path("src/b.py"), Path("src/c.py")]
    tests = [Path("tests/test_a.py")]

    result = mapper.map(sources, tests)
    assert set(result.keys()) == set(sources)


def test_multiple_test_files_for_one_source() -> None:
    """A source file can match multiple test files (prefix and suffix)."""
    mapper = TestFileMapper()
    source = [Path("src/auth.py")]
    tests = [Path("tests/test_auth.py"), Path("tests/auth_test.py")]

    result = mapper.map(source, tests)
    assert len(result[Path("src/auth.py")]) == 2
