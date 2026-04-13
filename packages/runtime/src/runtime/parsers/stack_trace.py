"""Generic stack trace parser — Python, Java, and .NET formats.

Parses free-form text that may contain one or more stack traces and
produces RuntimeSignal objects.  Each contiguous block of stack-trace
lines becomes one signal.
"""

from __future__ import annotations

import hashlib
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

# Structured frame extraction patterns
# Python: File "auth.py", line 42, in validate_token
_PY_FRAME_DETAIL = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
# Java: at com.example.Foo.bar(Foo.java:42)
_JAVA_FRAME_DETAIL = re.compile(r'at ([\w$.]+)\((\w+\.(?:java|kt|scala)):(\d+)\)')
# .NET: at Namespace.Class.Method() in /path/Foo.cs:line 42
_DOTNET_FRAME_DETAIL = re.compile(r'at ([\w.`<>[\]]+\(.*?\))\s+in (.+\.cs):line (\d+)')

# Normalization patterns for error_hash
_NORMALIZE_LINE_REFS = re.compile(r'\b(at\s+)?line[:\s]+\d+', re.IGNORECASE)
_NORMALIZE_MEMORY = re.compile(r'0x[0-9a-fA-F]+')
_NORMALIZE_DIGITS = re.compile(r'\b\d{3,}\b')  # long numbers (addresses, ports)


def _normalize_message(exc_name: str, message: str) -> str:
    """Normalize an exception message for stable hashing.

    Strips volatile parts (line numbers, memory addresses, long numeric IDs)
    so that the same logical error gets the same hash across runs.
    """
    text = f"{exc_name}: {message}"
    text = _NORMALIZE_LINE_REFS.sub("", text)
    text = _NORMALIZE_MEMORY.sub("", text)
    text = _NORMALIZE_DIGITS.sub("", text)
    # Collapse whitespace
    return " ".join(text.split()).lower()


def _make_error_hash(exc_name: str, message: str) -> str:
    """Return a 16-char SHA256 prefix of the normalized error signature."""
    normalized = _normalize_message(exc_name, message)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _extract_top_frames(lines: list[str], max_frames: int = 5) -> list[dict]:
    """Extract structured top-N stack frames from trace lines.

    Returns a list of dicts: [{"file": ..., "function": ..., "line": N}]
    """
    frames: list[dict] = []
    for line in lines:
        if len(frames) >= max_frames:
            break
        # Python
        m = _PY_FRAME_DETAIL.search(line)
        if m:
            frames.append({"file": m.group(1), "function": m.group(3), "line": int(m.group(2))})
            continue
        # Java
        m = _JAVA_FRAME_DETAIL.search(line)
        if m:
            frames.append({"file": m.group(2), "function": m.group(1).split(".")[-1], "line": int(m.group(3))})
            continue
        # .NET
        m = _DOTNET_FRAME_DETAIL.search(line)
        if m:
            fname = Path(m.group(2)).name
            frames.append({"file": fname, "function": m.group(1).split(".")[-1], "line": int(m.group(3))})
            continue
    return frames


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
    message, source, exc_name = _extract_message(text)
    paths = _extract_paths(lines)
    stack = [l.strip() for l in lines if l.strip()]
    top_frames = _extract_top_frames(stack)
    error_hash = _make_error_hash(exc_name, message) if exc_name else ""

    return RuntimeSignal(
        source=source,
        severity="error",
        message=message or "Stack trace detected",
        stack=stack,
        paths=paths,
        top_frames=top_frames,
        error_hash=error_hash,
    )


def _extract_message(text: str) -> tuple[str, str, str]:
    """Return (message, source_label, exc_name) from stack trace text."""
    # Check Java/dotnet before Python — their exception class names also satisfy
    # the Python pattern (e.g. java.lang.NullPointerException matches (?:\w+\.)*\w+Exception).
    for pattern, label in (
        (_JAVA_EXC, "java"),
        (_DOTNET_EXC, "dotnet"),
        (_PY_EXC, "python"),
    ):
        m = pattern.search(text)
        if m:
            exc = m.group("exc")
            msg = m.group("msg")
            return f"{exc}: {msg}", label, exc
    return "", "unknown", ""


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
