"""Markdown export for context-router observations and decisions.

Provides human-readable export for sharing team learnings without committing
the SQLite database. Supports optional redaction of sensitive paths and
commands for public sharing.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from contracts.models import Decision, Observation
from memory.freshness import effective_confidence


def _slugify(text: str) -> str:
    """Convert a title string to a URL-safe slug.

    Example: "Use SQLite for local storage" → "use-sqlite-for-local-storage"
    """
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def format_observation_md(obs: Observation, redact: bool = False) -> str:
    """Render one observation as a Markdown block.

    Args:
        obs: The observation to format.
        redact: If True, omit file paths, commands_run, and commit_sha.

    Returns:
        A Markdown string representing the observation.
    """
    eff = round(effective_confidence(obs), 3)
    age_days = (datetime.now(UTC) - obs.timestamp).days
    task_type = obs.task_type or "general"

    lines: list[str] = [
        f"### [{task_type}] {obs.summary}",
        "",
        f"- **Confidence:** {eff}  **Age:** {age_days}d  **Accesses:** {obs.access_count}",
    ]

    if not redact:
        if obs.commit_sha:
            lines.append(f"- **Commit:** `{obs.commit_sha}`")
        if obs.files_touched:
            lines.append(f"- **Files:** {', '.join(f'`{f}`' for f in obs.files_touched[:10])}")
        if obs.commands_run:
            lines.append(f"- **Commands:** {', '.join(f'`{c}`' for c in obs.commands_run[:5])}")

    if obs.fix_summary:
        lines.append(f"- **Fix:** {obs.fix_summary}")

    if obs.failures_seen:
        lines.append(f"- **Failures:** {'; '.join(obs.failures_seen[:3])}")

    lines.append("")
    return "\n".join(lines)


def format_decision_md(dec: Decision) -> str:
    """Render one decision as an ADR-style Markdown document.

    Args:
        dec: The Decision to format.

    Returns:
        A full Markdown document string.
    """
    date_str = dec.created_at.strftime("%Y-%m-%d")
    superseded_note = (
        f"\n> **Superseded by:** `{dec.superseded_by}`\n"
        if dec.superseded_by
        else ""
    )
    tags_str = ", ".join(f"`{t}`" for t in dec.tags) if dec.tags else "_none_"

    parts = [
        f"# {dec.title}",
        "",
        f"**Status:** {dec.status}  **Date:** {date_str}  **Confidence:** {dec.confidence}",
        superseded_note,
    ]

    if dec.context:
        parts += ["## Context", "", dec.context, ""]

    if dec.decision:
        parts += ["## Decision", "", dec.decision, ""]

    if dec.consequences:
        parts += ["## Consequences", "", dec.consequences, ""]

    parts += ["## Tags", "", tags_str, ""]

    return "\n".join(parts)


def export_observations(
    observations: list[Observation],
    output_path: Path,
    redact: bool = False,
    title: str = "Memory Export",
) -> int:
    """Write observations to a single Markdown file.

    Args:
        observations: Observations to export.
        output_path: Destination file path (parent directory must exist or
            will be created).
        redact: If True, strip file paths, commands, and commit SHAs.
        title: Document title used as the H1 header.

    Returns:
        Number of observations written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    redact_note = "  _(paths and commands redacted)_" if redact else ""

    header = [
        f"# {title}",
        "",
        f"_Generated {date_str}{redact_note} · {len(observations)} observation(s)_",
        "",
        "---",
        "",
    ]

    blocks = [format_observation_md(obs, redact=redact) for obs in observations]
    content = "\n".join(header) + "\n".join(blocks)
    output_path.write_text(content, encoding="utf-8")
    return len(observations)


def export_decisions_adr(
    decisions: list[Decision],
    output_dir: Path,
    statuses: list[str] | None = None,
) -> int:
    """Write one Markdown ADR file per decision to output_dir.

    Args:
        decisions: All decisions to consider for export.
        output_dir: Directory to write individual .md files into (created if needed).
        statuses: Only export decisions with these statuses. Defaults to
            ``["accepted"]``.

    Returns:
        Number of files written.
    """
    if statuses is None:
        statuses = ["accepted"]

    filtered = [d for d in decisions if d.status in statuses]
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, dec in enumerate(filtered, start=1):
        slug = _slugify(dec.title)[:60]
        filename = f"{i:04d}-{slug}.md"
        (output_dir / filename).write_text(format_decision_md(dec), encoding="utf-8")

    return len(filtered)
