"""Downstream read cost estimation for context packs.

Measures tokens an agent pays to *read* a pack's items:
- File-pointer items (lines=None): agent reads the whole file.
- Symbol-body items (lines=[start, end]): agent reads only those lines.

v4.3 baseline: file-pointer packs cost ~10,000 tokens downstream.
v4.4 target: symbol-body packs cost <=500 tokens downstream.
"""
from __future__ import annotations
from pathlib import Path

_CHARS_PER_TOKEN = 4  # conservative; matches ranking.estimator


def estimate_downstream_read_tokens(
    items: list[dict],  # [{"path": str, "lines": [start, end] | None}]
    project_root: Path,
) -> int:
    """Return total tokens agent must read to consume all items in the pack."""
    total = 0
    for item in items:
        raw = item.get("path", "")
        lines = item.get("lines")
        path = Path(raw) if Path(raw).is_absolute() else project_root / raw
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            all_lines = content.splitlines()
        except OSError:
            continue
        if lines and len(lines) == 2 and lines[0] and lines[1]:
            n_lines = max(0, int(lines[1]) - int(lines[0]) + 1)
        else:
            n_lines = len(all_lines)
        chars_per_line = len(content) / max(1, len(all_lines))
        total += max(1, int(n_lines * chars_per_line / _CHARS_PER_TOKEN))
    return total
