"""dotnet test output parser — converts VSTest/dotnet test stdout into RuntimeSignals.

Handles the text output produced by ``dotnet test`` / ``dotnet vstest``:

  Failed  MyNamespace.MyClass.MyTest
    Error Message:
       Assert.Equal() Failure
    Stack Trace:
       at MyNamespace.MyClass.MyTest() in /path/Foo.cs:line 42
"""

from __future__ import annotations

import re
from pathlib import Path

from contracts.models import RuntimeSignal

# "Failed  TestNamespace.TestClass.TestMethod"
_FAILED_LINE = re.compile(r'^(?:Failed|Error)\s+(?P<name>\S+)', re.MULTILINE)
# "Error Message:\n   <message>"
_MSG_BLOCK = re.compile(r'Error Message:\s*\n\s*(?P<msg>[^\n]+)', re.MULTILINE)
# .NET stack frame (leading whitespace optional — lines may be stripped)
_FRAME = re.compile(r'\s*at .+ in (?P<path>.+\.cs):line (?P<line>\d+)')


def parse_dotnet_output(text: str) -> list[RuntimeSignal]:
    """Parse ``dotnet test`` stdout into RuntimeSignal objects.

    Each failed test becomes one RuntimeSignal.

    Args:
        text: Full stdout from a ``dotnet test`` run.

    Returns:
        List of RuntimeSignal objects.
    """
    signals: list[RuntimeSignal] = []

    # Split on "Failed" test headers to find failure blocks
    blocks = re.split(r'^(?=(?:Failed|Error)\s+\S)', text, flags=re.MULTILINE)
    for block in blocks:
        m = _FAILED_LINE.match(block)
        if m is None:
            continue

        test_name = m.group("name")
        msg_m = _MSG_BLOCK.search(block)
        message = msg_m.group("msg").strip() if msg_m else "Test failed"

        stack_lines = [
            ln.strip()
            for ln in block.splitlines()
            if _FRAME.search(ln)
        ]
        paths = [
            Path(fm.group("path"))
            for ln in stack_lines
            for fm in [_FRAME.search(ln)]
            if fm
        ]

        signals.append(
            RuntimeSignal(
                source="dotnet",
                severity="error",
                message=f"{test_name}: {message}",
                stack=stack_lines,
                paths=paths,
            )
        )
    return signals


def parse_dotnet_output_file(path: Path) -> list[RuntimeSignal]:
    """Parse a saved dotnet test output file.

    Args:
        path: Path to the text file.

    Returns:
        List of RuntimeSignal objects.
    """
    try:
        return parse_dotnet_output(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
