"""Generic stack trace parser — Python, Java, and .NET formats.

Parses free-form text that may contain one or more stack traces and
produces RuntimeSignal objects.  Each contiguous block of stack-trace
lines becomes one signal.
"""

from __future__ import annotations

import re
from pathlib import Path

from contracts.models import RuntimeSignal

# -----------------------------------------------------------------------
# Regexes that identify lines as part of a stack trace
# -----------------------------------------------------------------------

# Python: "  File "foo.py", line 42, in bar"
_PY_FRAME = re.compile(r'\s*File "(?P<path>[^"]+)", line \d+')

# Python exception header: "SomeError: message" at start of block
_PY_EXC = re.compile(r'^(?:\w+\.)*(?P<exc>\w+Error|\w+Exception|\w+Warning):\s*(?P<msg>.+)', re.MULTILINE)

# Java: "  at com.example.Foo.bar(Foo.java:42)"
_JAVA_FRAME = re.compile(r'\s+at \S+\((?P<file>\w+\.(?:java|kt|scala)):\d+\)')

# Java exception header: "com.example.FooException: message"
_JAVA_EXC = re.compile(r'^(?:[\w.]+\.)?(?P<exc>\w+Exception|\w+Error):\s*(?P<msg>.+)', re.MULTILINE)

# .NET: "  at Namespace.Class.Method() in /path/Foo.cs:line 42"
_DOTNET_FRAME = re.compile(r'\s+at .+ in (?P<path>.+\.cs):line \d+')

# .NET exception header: "System.InvalidOperationException: message"
_DOTNET_EXC = re.compile(r'^(?:[\w.]+\.)?(?P<exc>\w+Exception):\s*(?P<msg>.+)', re.MULTILINE)

# A line is "in a stack trace" if it matches any frame pattern
_FRAME_PATTERNS = (_PY_FRAME, _JAVA_FRAME, _DOTNET_FRAME)

# Path patterns for extraction
_PATH_PY = re.compile(r'File "([^"]+)"')
_PATH_JAVA = re.compile(r'\((\w+\.(?:java|kt|scala)):\d+\)')
_PATH_DOTNET = re.compile(r'in (.+\.cs):line')


def parse_stack_trace(text: str) -> list[RuntimeSignal]:
    """Parse free-form text containing stack traces into RuntimeSignals.

    Detects Python, Java, and .NET stack trace blocks.  Each distinct
    block becomes one RuntimeSignal.

    Args:
        text: Raw text (error output, log file snippet, etc.).

    Returns:
        List of RuntimeSignal objects, one per detected stack trace block.
    """
    lines = text.splitlines()
    signals: list[RuntimeSignal] = []
    block: list[str] = []
    in_trace = False

    def _flush(block: list[str]) -> None:
        if not block:
            return
        sig = _block_to_signal(block)
        if sig is not None:
            signals.append(sig)

    for line in lines:
        is_frame = any(p.search(line) for p in _FRAME_PATTERNS)
        if is_frame:
            in_trace = True
            block.append(line)
        elif in_trace:
            # Continue block if it's a non-empty continuation line
            stripped = line.strip()
            if stripped:
                block.append(line)
            else:
                _flush(block)
                block = []
                in_trace = False
        else:
            # Keep potential exception header lines in a 1-line lookahead buffer
            if block:
                block.append(line)
            else:
                block = [line]

    _flush(block)
    return signals


def _block_to_signal(lines: list[str]) -> RuntimeSignal | None:
    """Convert a block of lines into a RuntimeSignal if it looks like a trace."""
    frame_count = sum(1 for l in lines if any(p.search(l) for p in _FRAME_PATTERNS))
    if frame_count == 0:
        return None

    text = "\n".join(lines)

    # Detect language and extract exception message
    message, source = _extract_message(text)
    paths = _extract_paths(lines)
    stack = [l.strip() for l in lines if l.strip()]

    return RuntimeSignal(
        source=source,
        severity="error",
        message=message or "Stack trace detected",
        stack=stack,
        paths=paths,
    )


def _extract_message(text: str) -> tuple[str, str]:
    """Return (message, source_label) from stack trace text."""
    # Check Java/dotnet before Python — their exception class names also satisfy
    # the Python pattern (e.g. java.lang.NullPointerException matches (?:\w+\.)*\w+Exception).
    for pattern, label in (
        (_JAVA_EXC, "java"),
        (_DOTNET_EXC, "dotnet"),
        (_PY_EXC, "python"),
    ):
        m = pattern.search(text)
        if m:
            return f"{m.group('exc')}: {m.group('msg')}", label
    return "", "unknown"


def _extract_paths(lines: list[str]) -> list[Path]:
    """Extract referenced file paths from stack trace lines."""
    paths: list[Path] = []
    seen: set[str] = set()
    for line in lines:
        for pattern in (_PATH_PY, _PATH_JAVA, _PATH_DOTNET):
            m = pattern.search(line)
            if m:
                p = m.group(1)
                if p not in seen:
                    seen.add(p)
                    paths.append(Path(p))
                break
    return paths
