"""Tests for Phase 4 debug signal enrichment — error_hash and top_frames."""

from __future__ import annotations

from runtime.parsers.stack_trace import (
    _extract_top_frames,
    _make_error_hash,
    _normalize_message,
    parse_stack_trace,
)
from runtime.parsers.junit_xml import parse_junit_xml


PYTHON_TRACE = """\
Traceback (most recent call last):
  File "auth/validate.py", line 42, in validate_token
    token = jwt.decode(raw, key)
  File "auth/jwt_helper.py", line 17, in decode
    raise ValueError("bad token")
ValueError: bad token
"""

JAVA_TRACE = """\
com.example.auth.TokenException: Invalid token at line 99
    at com.example.auth.JwtHelper.decode(JwtHelper.java:17)
    at com.example.auth.AuthService.validate(AuthService.java:42)
"""

JUNIT_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<testsuite name="auth_tests" tests="2" failures="1" errors="0">
  <testcase classname="test_auth" name="test_validate_token" time="0.05">
    <failure message="AssertionError: expected True">
      File "tests/test_auth.py", line 20, in test_validate_token
        assert validate_token("bad") is True
    </failure>
  </testcase>
  <testcase classname="test_auth" name="test_happy_path" time="0.02"/>
</testsuite>
"""


class TestNormalizeMessage:
    def test_strips_line_numbers(self):
        result = _normalize_message("ValueError", "bad token at line 42")
        assert "42" not in result

    def test_strips_memory_addresses(self):
        result = _normalize_message("SegFault", "address 0xDEADBEEF invalid")
        assert "0xdeadbeef" not in result

    def test_preserves_exception_name(self):
        result = _normalize_message("ValueError", "some message")
        assert "valueerror" in result

    def test_same_error_different_line_same_hash(self):
        h1 = _make_error_hash("ValueError", "bad token at line 42")
        h2 = _make_error_hash("ValueError", "bad token at line 99")
        assert h1 == h2

    def test_different_errors_different_hash(self):
        h1 = _make_error_hash("ValueError", "bad token")
        h2 = _make_error_hash("KeyError", "missing key")
        assert h1 != h2

    def test_hash_is_16_chars(self):
        h = _make_error_hash("ValueError", "some error")
        assert len(h) == 16


class TestExtractTopFrames:
    def test_extracts_python_frames(self):
        lines = [
            '  File "auth/validate.py", line 42, in validate_token',
            '  File "auth/jwt_helper.py", line 17, in decode',
        ]
        frames = _extract_top_frames(lines)
        assert len(frames) == 2
        assert frames[0]["file"] == "auth/validate.py"
        assert frames[0]["function"] == "validate_token"
        assert frames[0]["line"] == 42

    def test_caps_at_max_frames(self):
        lines = [
            '  File "a.py", line 1, in f1',
            '  File "b.py", line 2, in f2',
            '  File "c.py", line 3, in f3',
            '  File "d.py", line 4, in f4',
            '  File "e.py", line 5, in f5',
            '  File "f.py", line 6, in f6',
        ]
        frames = _extract_top_frames(lines, max_frames=5)
        assert len(frames) == 5

    def test_extracts_java_frames(self):
        lines = [
            "    at com.example.auth.JwtHelper.decode(JwtHelper.java:17)",
        ]
        frames = _extract_top_frames(lines)
        assert len(frames) == 1
        assert frames[0]["file"] == "JwtHelper.java"
        assert frames[0]["line"] == 17

    def test_empty_returns_empty(self):
        assert _extract_top_frames([]) == []


class TestParseStackTraceEnriched:
    def test_python_trace_has_error_hash(self):
        signals = parse_stack_trace(PYTHON_TRACE)
        assert len(signals) >= 1
        assert signals[0].error_hash != ""
        assert len(signals[0].error_hash) == 16

    def test_python_trace_has_top_frames(self):
        signals = parse_stack_trace(PYTHON_TRACE)
        assert len(signals[0].top_frames) >= 1
        assert signals[0].top_frames[0]["file"] == "auth/validate.py"

    def test_java_trace_has_error_hash(self):
        signals = parse_stack_trace(JAVA_TRACE)
        assert len(signals) >= 1
        assert signals[0].error_hash != ""

    def test_same_error_same_hash_across_parses(self):
        sigs1 = parse_stack_trace(PYTHON_TRACE)
        sigs2 = parse_stack_trace(PYTHON_TRACE.replace("line 42", "line 99"))
        assert sigs1[0].error_hash == sigs2[0].error_hash


class TestJUnitXMLEnriched:
    def test_has_error_hash(self):
        signals = parse_junit_xml(JUNIT_XML)
        assert len(signals) == 1
        assert signals[0].error_hash != ""

    def test_has_failing_tests(self):
        signals = parse_junit_xml(JUNIT_XML)
        assert signals[0].failing_tests == ["test_auth.test_validate_token"]

    def test_only_failures_produce_signals(self):
        signals = parse_junit_xml(JUNIT_XML)
        assert len(signals) == 1  # one failure, one pass → only failure
