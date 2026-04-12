"""Tests for runtime evidence parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from contracts.models import RuntimeSignal
from runtime import parse_error_file
from runtime.parsers.dotnet import parse_dotnet_output
from runtime.parsers.junit_xml import parse_junit_xml
from runtime.parsers.log import parse_log
from runtime.parsers.stack_trace import parse_stack_trace

# -----------------------------------------------------------------------
# JUnit XML
# -----------------------------------------------------------------------

_JUNIT_XML_ONE_FAILURE = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuite name="test_foo" tests="2" failures="1" errors="0">
  <testcase classname="test_foo" name="test_passes" time="0.001"/>
  <testcase classname="test_foo" name="test_fails" time="0.002">
    <failure message="AssertionError: 1 != 2">
      File "src/foo.py", line 10, in test_fails
        assert 1 == 2
      AssertionError: 1 != 2
    </failure>
  </testcase>
</testsuite>
"""

_JUNIT_XML_NO_FAILURES = """\
<testsuite name="suite" tests="1" failures="0">
  <testcase classname="t" name="pass_test"/>
</testsuite>
"""

_JUNIT_XML_TESTSUITES_WRAPPER = """\
<testsuites>
  <testsuite name="s1">
    <testcase classname="A" name="a">
      <failure message="boom">stack here</failure>
    </testcase>
  </testsuite>
  <testsuite name="s2">
    <testcase classname="B" name="b">
      <error message="err">err stack</error>
    </testcase>
  </testsuite>
</testsuites>
"""


def test_junit_xml_one_failure() -> None:
    sigs = parse_junit_xml(_JUNIT_XML_ONE_FAILURE)
    assert len(sigs) == 1
    assert "test_fails" in sigs[0].message
    assert sigs[0].severity == "error"


def test_junit_xml_no_failures_returns_empty() -> None:
    assert parse_junit_xml(_JUNIT_XML_NO_FAILURES) == []


def test_junit_xml_testsuites_wrapper() -> None:
    sigs = parse_junit_xml(_JUNIT_XML_TESTSUITES_WRAPPER)
    assert len(sigs) == 2


def test_junit_xml_extracts_python_path() -> None:
    sigs = parse_junit_xml(_JUNIT_XML_ONE_FAILURE)
    assert any(str(p).endswith("foo.py") for p in sigs[0].paths)


def test_junit_xml_invalid_xml_returns_empty() -> None:
    assert parse_junit_xml("not xml at all <<>>") == []


def test_junit_xml_file(tmp_path: Path) -> None:
    f = tmp_path / "report.xml"
    f.write_text(_JUNIT_XML_ONE_FAILURE)
    from runtime.parsers.junit_xml import parse_junit_xml_file
    sigs = parse_junit_xml_file(f)
    assert len(sigs) == 1


# -----------------------------------------------------------------------
# Stack trace
# -----------------------------------------------------------------------

_PYTHON_TRACE = """\
Traceback (most recent call last):
  File "src/core/orchestrator.py", line 42, in build_pack
    result = ranker.rank(items, query, mode)
  File "src/ranking/ranker.py", line 15, in rank
    raise ValueError("bad input")
ValueError: bad input
"""

_JAVA_TRACE = """\
java.lang.NullPointerException: Cannot invoke method on null
    at com.example.service.UserService.getUser(UserService.java:88)
    at com.example.controller.UserController.handle(UserController.java:55)
"""

_DOTNET_TRACE = """\
System.InvalidOperationException: Sequence contains no elements
   at MyApp.Services.DataService.GetFirst() in /app/Services/DataService.cs:line 99
   at MyApp.Controllers.DataController.Index() in /app/Controllers/DataController.cs:line 34
"""


def test_python_stack_trace_detected() -> None:
    sigs = parse_stack_trace(_PYTHON_TRACE)
    assert len(sigs) >= 1
    sig = sigs[0]
    assert "ValueError" in sig.message or sig.source == "python"


def test_python_stack_trace_paths() -> None:
    sigs = parse_stack_trace(_PYTHON_TRACE)
    all_paths = [str(p) for s in sigs for p in s.paths]
    assert any("orchestrator.py" in p for p in all_paths)


def test_java_stack_trace_detected() -> None:
    sigs = parse_stack_trace(_JAVA_TRACE)
    assert len(sigs) >= 1
    assert sigs[0].source == "java"


def test_dotnet_stack_trace_detected() -> None:
    sigs = parse_stack_trace(_DOTNET_TRACE)
    assert len(sigs) >= 1
    sig = sigs[0]
    assert "InvalidOperationException" in sig.message
    assert any("DataService.cs" in str(p) for p in sig.paths)


def test_plain_text_no_trace_returns_empty() -> None:
    sigs = parse_stack_trace("Nothing special here.\nJust regular text.")
    assert sigs == []


# -----------------------------------------------------------------------
# Log parser
# -----------------------------------------------------------------------

_LOG_TEXT = """\
2024-01-01 10:00:00 INFO  app.service: Started
2024-01-01 10:00:01 ERROR app.db: Connection refused to postgres:5432
2024-01-01 10:00:02 WARN  app.cache: Cache miss for key user:42
2024-01-01 10:00:03 INFO  app.service: Retry 1
2024-01-01 10:00:04 CRITICAL app.service: Fatal error, shutting down
"""


def test_log_extracts_errors() -> None:
    sigs = parse_log(_LOG_TEXT)
    error_sigs = [s for s in sigs if s.severity == "error"]
    assert len(error_sigs) >= 2  # ERROR + CRITICAL


def test_log_extracts_warnings() -> None:
    sigs = parse_log(_LOG_TEXT)
    warn_sigs = [s for s in sigs if s.severity == "warning"]
    assert len(warn_sigs) >= 1


def test_log_info_lines_ignored() -> None:
    sigs = parse_log(_LOG_TEXT)
    assert all("INFO" not in s.message.upper() or s.severity != "info" for s in sigs)


def test_log_empty_text_returns_empty() -> None:
    assert parse_log("") == []


# -----------------------------------------------------------------------
# dotnet output
# -----------------------------------------------------------------------

_DOTNET_OUTPUT = """\
  Determining projects to restore...
  All projects are up-to-date for restore.
  MyProject.Tests -> bin/Debug/net8.0/MyProject.Tests.dll
Test run for MyProject.Tests.dll (.NETCoreApp,Version=v8.0)
Microsoft (R) Test Execution Command Line Tool Version 17.0
Copyright (c) Microsoft Corporation.  All rights reserved.

Starting test execution, please wait...

Failed  MyNamespace.MyTests.TestSomething
  Error Message:
     Assert.Equal() Failure
     Expected: 42
     Actual:   0
  Stack Trace:
     at MyNamespace.MyTests.TestSomething() in /app/Tests/MyTests.cs:line 25
"""


def test_dotnet_output_detects_failure() -> None:
    sigs = parse_dotnet_output(_DOTNET_OUTPUT)
    assert len(sigs) == 1
    assert "TestSomething" in sigs[0].message


def test_dotnet_output_extracts_path() -> None:
    sigs = parse_dotnet_output(_DOTNET_OUTPUT)
    assert any("MyTests.cs" in str(p) for p in sigs[0].paths)


def test_dotnet_output_no_failures_returns_empty() -> None:
    assert parse_dotnet_output("All tests passed.") == []


# -----------------------------------------------------------------------
# parse_error_file auto-detection
# -----------------------------------------------------------------------

def test_parse_error_file_xml(tmp_path: Path) -> None:
    f = tmp_path / "report.xml"
    f.write_text(_JUNIT_XML_ONE_FAILURE)
    sigs = parse_error_file(f)
    assert len(sigs) == 1


def test_parse_error_file_log(tmp_path: Path) -> None:
    f = tmp_path / "app.log"
    f.write_text(_LOG_TEXT)
    sigs = parse_error_file(f)
    assert len(sigs) >= 1


def test_parse_error_file_stack_trace_txt(tmp_path: Path) -> None:
    f = tmp_path / "error.txt"
    f.write_text(_PYTHON_TRACE)
    sigs = parse_error_file(f)
    assert len(sigs) >= 1


def test_parse_error_file_missing_returns_empty(tmp_path: Path) -> None:
    sigs = parse_error_file(tmp_path / "nonexistent.xml")
    assert sigs == []
