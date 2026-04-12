"""Log file parser — extracts ERROR and WARN lines as RuntimeSignals.

Handles common log formats:
  - Python logging: "2024-01-01 12:00:00 ERROR module: message"
  - Java/Logback: "2024-01-01 12:00:00.000 ERROR c.e.Class - message"
  - Generic: any line containing "ERROR" or "WARN"
"""

from __future__ import annotations

import re
from pathlib import Path

from contracts.models import RuntimeSignal

_SEVERITY_PATTERN = re.compile(
    r'\b(?P<level>ERROR|WARN(?:ING)?|CRITICAL|FATAL|SEVERE)\b',
    re.IGNORECASE,
)

# Path-like tokens in log lines (e.g. "at foo/bar.py:42" or "/var/log/...")
_PATH_IN_LOG = re.compile(r'(?:File "([^"]+)"|(\S+\.(?:py|java|cs|kt|rb|go|ts|js)))')


def parse_log(text: str) -> list[RuntimeSignal]:
    """Parse a log text and return one RuntimeSignal per ERROR/WARN line.

    Lines that contain ERROR, WARN, WARNING, CRITICAL, FATAL, or SEVERE are
    each converted to a RuntimeSignal.  Severity mapping:

      ERROR / CRITICAL / FATAL / SEVERE → "error"
      WARN / WARNING → "warning"

    Args:
        text: Raw log text.

    Returns:
        List of RuntimeSignal objects, one per matching line.
    """
    signals: list[RuntimeSignal] = []
    for line in text.splitlines():
        m = _SEVERITY_PATTERN.search(line)
        if m is None:
            continue
        level = m.group("level").upper()
        severity: str
        if level in ("WARN", "WARNING"):
            severity = "warning"
        else:
            severity = "error"

        message = line.strip()
        paths = _extract_paths(line)
        signals.append(
            RuntimeSignal(
                source="log",
                severity=severity,  # type: ignore[arg-type]
                message=message[:500],
                paths=paths,
            )
        )
    return signals


def parse_log_file(path: Path) -> list[RuntimeSignal]:
    """Parse a log file and return RuntimeSignals.

    Args:
        path: Path to the log file.

    Returns:
        List of RuntimeSignal objects.
    """
    try:
        return parse_log(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []


def _extract_paths(line: str) -> list[Path]:
    """Extract file paths referenced in a log line."""
    paths: list[Path] = []
    for m in _PATH_IN_LOG.finditer(line):
        p = m.group(1) or m.group(2)
        if p:
            paths.append(Path(p))
    return paths
