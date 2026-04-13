"""JUnit XML parser — converts test failure XML into RuntimeSignal objects.

Handles both pytest's JUnit XML output (--junit-xml) and Maven/Gradle
Surefire reports.  The XML schema is compatible across all these tools:

  <testsuite name="..." tests="3" failures="1" errors="0">
    <testcase classname="test_foo" name="test_bar" time="0.1">
      <failure message="AssertionError">  traceback here  </failure>
    </testcase>
  </testsuite>
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

from contracts.models import RuntimeSignal


def _make_error_hash(test_name: str, message: str) -> str:
    """Return a 16-char SHA256 prefix of the normalized test failure signature."""
    normalized = f"{test_name}:{message}".lower().strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def parse_junit_xml(xml_text: str) -> list[RuntimeSignal]:
    """Parse JUnit XML report text into RuntimeSignal objects.

    Only failed test cases produce signals.  Each failure or error element
    becomes one RuntimeSignal with ``source="junit"``.

    Args:
        xml_text: Raw XML string from a JUnit-compatible test report.

    Returns:
        List of RuntimeSignal objects, one per failed test case.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    # Support both <testsuite> at root and <testsuites> wrapper
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    signals: list[RuntimeSignal] = []
    for suite in suites:
        suite_name = suite.get("name", "")
        for tc in suite.findall("testcase"):
            classname = tc.get("classname", "")
            testname = tc.get("name", "")
            full_name = f"{classname}.{testname}" if classname else testname

            for outcome_tag in ("failure", "error"):
                child = tc.find(outcome_tag)
                if child is None:
                    continue
                message = child.get("message", "") or (child.text or "").strip()[:200]
                stack_text = (child.text or "").strip()
                stack_lines = [ln.strip() for ln in stack_text.splitlines() if ln.strip()]
                paths = _extract_paths(stack_lines)
                error_hash = _make_error_hash(full_name, message)
                signals.append(
                    RuntimeSignal(
                        source=f"junit:{suite_name}",
                        severity="error",
                        message=f"{full_name}: {message}",
                        stack=stack_lines,
                        paths=paths,
                        error_hash=error_hash,
                        failing_tests=[full_name],
                    )
                )
    return signals


def parse_junit_xml_file(path: Path) -> list[RuntimeSignal]:
    """Parse a JUnit XML file and return RuntimeSignals.

    Args:
        path: Path to the XML file.

    Returns:
        List of RuntimeSignal objects.
    """
    try:
        return parse_junit_xml(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def _extract_paths(stack_lines: list[str]) -> list[Path]:
    """Extract file paths mentioned in a stack trace.

    Looks for lines of the form:
      File "path/to/file.py", line N  (Python)
      at com.example.Foo(Foo.java:42)  (Java — extracts .java filename)
      at Foo.cs:42                     (.NET)

    Args:
        stack_lines: Lines from a stack trace.

    Returns:
        List of Path objects (may be relative).
    """
    import re

    paths: list[Path] = []
    py_pattern = re.compile(r'File "([^"]+)", line \d+')
    java_pattern = re.compile(r'\((\w+\.(?:java|kt|scala)):\d+\)')
    dotnet_pattern = re.compile(r'in (.+\.cs):line \d+')

    for line in stack_lines:
        for pattern in (py_pattern, java_pattern, dotnet_pattern):
            m = pattern.search(line)
            if m:
                paths.append(Path(m.group(1)))
                break
    return paths
