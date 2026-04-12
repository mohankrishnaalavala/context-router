"""context-router-runtime: runtime evidence parsers (Phase 3).

Parses test output (JUnit XML, dotnet) and free-form text (stack traces,
log files) into RuntimeSignal objects for use by the debug-mode ranker.
"""

from __future__ import annotations

from pathlib import Path

from contracts.models import RuntimeSignal
from runtime.parsers.dotnet import parse_dotnet_output, parse_dotnet_output_file
from runtime.parsers.junit_xml import parse_junit_xml, parse_junit_xml_file
from runtime.parsers.log import parse_log, parse_log_file
from runtime.parsers.stack_trace import parse_stack_trace


def parse_error_file(path: Path) -> list[RuntimeSignal]:
    """Auto-detect format and parse *path* into RuntimeSignals.

    Detection rules (by file extension):
    - ``.xml`` → JUnit XML
    - ``.log`` → log parser + stack trace parser
    - Everything else → stack trace + log parser combined

    Args:
        path: Path to the error file.

    Returns:
        List of RuntimeSignal objects.  Empty list if the file cannot be parsed.
    """
    if not path.exists():
        return []

    ext = path.suffix.lower()
    if ext == ".xml":
        return parse_junit_xml_file(path)

    text = path.read_text(encoding="utf-8", errors="replace")

    # Try dotnet format first (it has distinctive "Failed  " lines)
    dotnet_signals = parse_dotnet_output(text)
    if dotnet_signals:
        return dotnet_signals

    # Combine stack trace + log signals (deduplicate by message)
    seen: set[str] = set()
    signals: list[RuntimeSignal] = []
    for sig in parse_stack_trace(text) + parse_log(text):
        if sig.message not in seen:
            seen.add(sig.message)
            signals.append(sig)
    return signals


__all__ = [
    "parse_error_file",
    "parse_junit_xml",
    "parse_junit_xml_file",
    "parse_dotnet_output",
    "parse_dotnet_output_file",
    "parse_log",
    "parse_log_file",
    "parse_stack_trace",
]
