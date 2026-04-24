"""Git-tracked Markdown file writer for memory observations.

When an observation passes the write gate, this module writes a .md file
with YAML frontmatter under ``<memory_dir>/observations/`` and keeps a
top-level ``MEMORY.md`` index up to date.

The write gate rejects observations that are:
- Too short (summary < 60 chars after stripping)
- Not touching any files (empty files_touched list)
- Tagged as scratch work (task_type == "scratch")

Silent failures are explicitly surfaced on stderr — see :func:`WriteResult`.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from contracts.models import Observation


@dataclass
class WriteResult:
    """Result of a :meth:`MemoryFileWriter.write_observation` call.

    Attributes:
        written: True if the file was written (or already existed).
        path: Absolute path of the written file, or None on rejection.
        reason: Human-readable rejection reason when written is False.
    """

    written: bool
    path: Path | None
    reason: str = ""


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert *text* to a URL-safe slug.

    Steps:
    1. Lowercase.
    2. Replace spaces with hyphens.
    3. Strip any character that is not alphanumeric or a hyphen.
    4. Truncate to *max_len*.
    """
    slug = text.lower()[:max_len]
    slug = slug.replace(" ", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    # Collapse consecutive hyphens that may arise after stripping
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")


class MemoryFileWriter:
    """Writes observations as git-tracked Markdown files.

    Args:
        memory_dir: The ``.context-router/memory`` directory.  The
            ``observations/`` sub-directory is created on first write.
    """

    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def write_observation(self, obs: "Observation") -> WriteResult:
        """Write *obs* as a ``.md`` file under ``observations/``.

        Write gate (any of these causes rejection with written=False):
        1. ``len(obs.summary.strip()) < 60``
        2. ``not obs.files_touched`` (empty list)
        3. ``obs.task_type == "scratch"``

        On rejection a warning is printed to stderr and a :class:`WriteResult`
        with ``written=False`` is returned — the caller should NOT treat this
        as a hard error.

        If the target file already exists the call is idempotent: the file is
        *not* overwritten and ``written=True`` is returned with the existing
        path so callers receive a consistent result.

        Args:
            obs: Observation to persist.

        Returns:
            :class:`WriteResult` describing what happened.
        """
        # --- write gate ---------------------------------------------------
        rejection = self._check_gate(obs)
        if rejection:
            print(f"warning: observation refused: {rejection}", file=sys.stderr)
            return WriteResult(written=False, path=None, reason=rejection)

        # --- derive file name ---------------------------------------------
        date_str = obs.timestamp.strftime("%Y-%m-%d")
        slug = _slugify(obs.summary)
        filename = f"{date_str}-{slug}.md"

        observations_dir = self._memory_dir / "observations"
        observations_dir.mkdir(parents=True, exist_ok=True)
        dest = observations_dir / filename

        # --- idempotency --------------------------------------------------
        if dest.exists():
            return WriteResult(written=True, path=dest)

        # --- render file --------------------------------------------------
        content = self._render(obs, date_str, slug)
        dest.write_text(content, encoding="utf-8")
        return WriteResult(written=True, path=dest)

    def update_index(self) -> None:
        """Regenerate ``MEMORY.md`` as a one-line-per-observation index.

        Scans all ``.md`` files in ``observations/``, sorts them newest-first
        (descending by filename), and writes (or overwrites) ``MEMORY.md``
        in ``memory_dir``.

        Format per entry::

            - [stem](observations/filename.md) — summary[:80]

        The summary is read from the file body (first non-empty line after
        the closing ``---`` of the frontmatter block).
        """
        observations_dir = self._memory_dir / "observations"
        if not observations_dir.exists():
            return

        entries: list[tuple[str, Path]] = []
        for md_file in sorted(observations_dir.glob("*.md"), reverse=True):
            summary_line = self._extract_summary(md_file)
            entries.append((md_file.stem, md_file))

        lines = ["# Memory Index\n\n"]
        for stem, md_file in entries:
            rel = md_file.relative_to(self._memory_dir)
            summary_line = self._extract_summary(md_file)
            lines.append(f"- [{stem}]({rel}) — {summary_line[:80]}\n")

        index_path = self._memory_dir / "MEMORY.md"
        index_path.write_text("".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_gate(obs: "Observation") -> str:
        """Return a non-empty rejection reason, or empty string if OK."""
        if len(obs.summary.strip()) < 60:
            return "summary too short (< 60 chars)"
        if not obs.files_touched:
            return "files_touched is empty"
        if obs.task_type == "scratch":
            return "task_type is 'scratch'"
        return ""

    @staticmethod
    def _render(obs: "Observation", date_str: str, slug: str) -> str:
        """Render the full Markdown content for *obs*."""
        obs_id = f"{date_str}-{slug}"
        task = obs.task_type or "general"
        created_at = obs.timestamp.isoformat()

        # Build YAML files_touched block
        files_lines = "\n".join(f"  - {f}" for f in obs.files_touched)

        frontmatter = (
            f"---\n"
            f"id: {obs_id}\n"
            f"type: observation\n"
            f"task: {task}\n"
            f"files_touched:\n{files_lines}\n"
            f"created_at: {created_at}\n"
            f"author: context-router\n"
            f"---\n"
        )

        body_parts = [obs.summary]
        if obs.fix_summary and obs.fix_summary.strip():
            body_parts.append(obs.fix_summary)

        body = "\n\n".join(body_parts) + "\n"
        return frontmatter + "\n" + body

    @staticmethod
    def _extract_summary(md_file: Path) -> str:
        """Return the first non-empty body line of a frontmatter .md file."""
        try:
            text = md_file.read_text(encoding="utf-8")
        except OSError:
            return md_file.stem

        # Find the closing --- of the frontmatter
        parts = text.split("---\n", 2)
        if len(parts) < 3:
            # No proper frontmatter — use first non-empty line
            for line in text.splitlines():
                stripped = line.strip()
                if stripped:
                    return stripped
            return md_file.stem

        body = parts[2]
        for line in body.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return md_file.stem
