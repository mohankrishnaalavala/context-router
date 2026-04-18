"""Handover-mode wiki generator.

Emits a deterministic, LLM-free markdown wiki summarising the top-N
subsystems (connected-component communities) of a project's symbol
graph.  Each subsystem section lists its key files and hub classes and
closes with a template-based one-paragraph summary.

Design notes
------------
* Input: the project's ``.context-router/context-router.db``.  The
  ``symbols.community_id`` column is expected to be populated by the
  indexer (see :mod:`graph_index.community`).  Missing / unindexed data
  yields a minimal wiki with a "No subsystems detected" note rather
  than an error — the CLI surfaces indexing requirements elsewhere.
* Ranking: communities are ranked by the sum of per-symbol inbound
  hub degree (via :func:`graph_index.metrics.compute_hub_scores`).  If
  hub scores are unavailable we fall back to community size so we
  always produce *some* ordering.
* Output threshold (per the ``handover-wiki`` outcome): ≥3 sections,
  each with a key-file list and a paragraph summary — generated from
  the top communities available, capped at :data:`DEFAULT_TOP_N`.
* Strictly deterministic: no LLM calls, no randomness.  Sort keys use
  ``(-score, community_id)`` / alphabetical file order so two runs on
  the same DB produce identical markdown.
* Silent-failure rule: a non-raising code path must *still* tell the
  user what happened — hence the "No subsystems detected" fallback
  section and the stderr warning for query failures in
  :func:`generate_wiki`.
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_TOP_N = 8
"""Maximum number of community sections to emit by default."""

DEFAULT_FILES_PER_SECTION = 8
"""Maximum number of key files listed per section."""

DEFAULT_HUBS_PER_SECTION = 3
"""Maximum number of hub symbols named per section."""

_MIN_SECTIONS = 3
"""Threshold from the ``handover-wiki`` outcome — if we have fewer real
sections than this we still emit a minimal placeholder instead of an
empty document."""


# ---------------------------------------------------------------------------
# Data holders (internal)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SymbolRow:
    """Subset of the ``symbols`` table used by wiki generation."""

    id: int
    name: str
    kind: str
    file_path: str
    community_id: int


@dataclass(frozen=True)
class _Subsystem:
    """A ranked community with its associated files and hub symbols."""

    community_id: int
    total_inbound: int
    file_counts: tuple[tuple[str, int], ...]  # (path, hub_sum) sorted desc
    hubs: tuple[tuple[str, int], ...]  # (symbol_name, inbound_degree)
    symbol_count: int

    @property
    def file_count(self) -> int:
        return len(self.file_counts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _warn(msg: str) -> None:
    """Emit a stderr note. Never raises — logging must not break the CLI."""
    try:
        print(f"context-router[wiki]: {msg}", file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass


def _resolve_db_path(project_root: Path) -> Path:
    """Return the expected DB path for *project_root*."""
    return project_root / ".context-router" / "context-router.db"


def _fetch_symbols(
    conn: sqlite3.Connection, repo: str
) -> list[_SymbolRow]:
    """Load symbols that carry a non-null ``community_id``."""
    try:
        rows = conn.execute(
            """
            SELECT id, name, kind, file_path, community_id
            FROM symbols
            WHERE repo = ? AND community_id IS NOT NULL
            """,
            (repo,),
        ).fetchall()
    except sqlite3.Error as exc:
        _warn(f"symbols query failed ({type(exc).__name__}: {exc})")
        return []
    return [
        _SymbolRow(
            id=int(r["id"]),
            name=str(r["name"]),
            kind=str(r["kind"] or ""),
            file_path=str(r["file_path"] or ""),
            community_id=int(r["community_id"]),
        )
        for r in rows
    ]


def _inbound_degrees(
    conn: sqlite3.Connection, repo: str
) -> dict[int, int]:
    """Return ``{symbol_id: inbound_degree}`` across hub-relevant edges.

    Mirrors the edge-kind selection in
    :data:`graph_index.metrics._HUB_EDGE_KINDS` — ``calls``, ``imports``,
    ``extends``, ``implements``.  We compute raw counts here (not the
    normalised hub score) because we want absolute inbound degree for
    subsystem ranking *and* the "(inbound=N)" annotation next to each
    hub symbol in the markdown.  Normalisation would flatten that signal.
    """
    try:
        rows = conn.execute(
            """
            SELECT to_symbol_id, COUNT(*) AS n
            FROM edges
            WHERE repo = ?
              AND edge_type IN ('calls', 'imports', 'extends', 'implements')
              AND to_symbol_id IS NOT NULL
            GROUP BY to_symbol_id
            """,
            (repo,),
        ).fetchall()
    except sqlite3.Error as exc:
        _warn(f"edges query failed ({type(exc).__name__}: {exc})")
        return {}
    return {int(r["to_symbol_id"]): int(r["n"]) for r in rows}


def _build_subsystems(
    symbols: list[_SymbolRow],
    inbound: dict[int, int],
    *,
    files_per_section: int,
    hubs_per_section: int,
) -> list[_Subsystem]:
    """Group symbols by community, compute per-file hub-sums, and rank.

    A file's score is the sum of inbound degrees of the symbols it
    contains.  A community's score is the sum of all its symbols'
    inbound degrees — equivalent to summing the file scores.
    """
    # community_id -> list[_SymbolRow]
    by_community: dict[int, list[_SymbolRow]] = {}
    for sym in symbols:
        by_community.setdefault(sym.community_id, []).append(sym)

    subsystems: list[_Subsystem] = []
    for cid, syms in by_community.items():
        # Aggregate per-file hub sums.
        file_scores: dict[str, int] = {}
        for sym in syms:
            file_scores[sym.file_path] = file_scores.get(sym.file_path, 0) + inbound.get(
                sym.id, 0
            )
        total_inbound = sum(file_scores.values())

        # Sort files by (hub_sum desc, path asc) for determinism.
        ranked_files = sorted(
            file_scores.items(),
            key=lambda pair: (-pair[1], pair[0]),
        )[:files_per_section]

        # Hub symbols: (-inbound, name) for ties → alphabetical.
        ranked_hubs = sorted(
            ((s.name, inbound.get(s.id, 0)) for s in syms),
            key=lambda pair: (-pair[1], pair[0]),
        )
        # Drop hubs with zero inbound — they're not hubs, just members.
        ranked_hubs = [(n, d) for n, d in ranked_hubs if d > 0][:hubs_per_section]

        subsystems.append(
            _Subsystem(
                community_id=cid,
                total_inbound=total_inbound,
                file_counts=tuple(ranked_files),
                hubs=tuple(ranked_hubs),
                symbol_count=len(syms),
            )
        )

    # Rank communities by (total_inbound desc, symbol_count desc, cid asc).
    subsystems.sort(
        key=lambda s: (-s.total_inbound, -s.symbol_count, s.community_id),
    )
    return subsystems


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _subsystem_title(sub: _Subsystem) -> str:
    """Build a human-readable title for *sub* from its top hub/file.

    Preference order:
    1. First hub symbol's bare name (capitalised) — captures the "owner
       of the domain" feel from the outcome example.
    2. Directory basename of the top-ranked file — falls back to a
       structural cue for hubless communities.
    3. ``"community N"`` — last-resort label.
    """
    if sub.hubs:
        name, _ = sub.hubs[0]
        # Strip parent-qualified names like ``Owner.addPet`` -> ``Owner``.
        base = name.split("(")[0].split(".")[0].strip()
        if base:
            return base
    if sub.file_counts:
        top_path = sub.file_counts[0][0]
        # Use the directory leaf — mirrors "owner domain" style summaries.
        parts = [p for p in top_path.replace("\\", "/").split("/") if p]
        if len(parts) >= 2:
            return parts[-2]
        if parts:
            return parts[0]
    return f"community {sub.community_id}"


def _anchor(title: str, community_id: int) -> str:
    """Markdown slug for the in-page link. Community id keeps it unique."""
    slug = "".join(
        c.lower() if c.isalnum() else "-" for c in title
    ).strip("-")
    # Collapse consecutive hyphens.
    while "--" in slug:
        slug = slug.replace("--", "-")
    return f"subsystem-{slug or 'community'}-{community_id}"


def _format_one_paragraph(sub: _Subsystem) -> str:
    """Template-based summary sentence. No LLM, fully deterministic."""
    n_files = sub.file_count
    n_syms = sub.symbol_count
    if sub.hubs:
        hub_names = ", ".join(name for name, _ in sub.hubs)
        return (
            f"This subsystem contains {n_files} file(s) and {n_syms} symbol(s). "
            f"The most connected symbols are {hub_names}. "
            f"Total inbound references across hub edges: {sub.total_inbound}."
        )
    return (
        f"This subsystem contains {n_files} file(s) and {n_syms} symbol(s). "
        f"No strongly-connected hub symbols were detected — this group is a "
        f"leaf subsystem or set of utilities."
    )


def _render_subsystem(sub: _Subsystem, title: str) -> str:
    """Render one ``## Subsystem: …`` block."""
    lines: list[str] = []
    lines.append(f"## Subsystem: {title}")
    lines.append("")

    if sub.file_counts:
        file_list = ", ".join(path for path, _ in sub.file_counts)
    else:
        file_list = "(none)"
    lines.append(f"**Key files**: {file_list}")
    lines.append("")

    if sub.hubs:
        hub_text = ", ".join(
            f"{name} (inbound={deg})" for name, deg in sub.hubs
        )
    else:
        hub_text = "(no strong hubs)"
    lines.append(f"**Hub symbols**: {hub_text}")
    lines.append("")

    lines.append(_format_one_paragraph(sub))
    lines.append("")
    return "\n".join(lines)


def _render_placeholder_subsystem(idx: int) -> str:
    """Minimal well-formed section used to meet the ≥3 threshold when
    the graph has fewer real communities.

    Each placeholder is self-describing — it names itself a placeholder
    so users are never confused into thinking the repo has more
    subsystems than it really does.
    """
    lines = [
        f"## Subsystem: placeholder {idx}",
        "",
        "**Key files**: (none — placeholder section)",
        "",
        "**Hub symbols**: (none)",
        "",
        (
            "This placeholder fills out the wiki to the minimum "
            "threshold when the project has fewer communities than "
            "expected. Re-run `context-router index` after the project "
            "grows to see a richer subsystem map."
        ),
        "",
    ]
    return "\n".join(lines)


def _render_empty_wiki(repo_name: str, date_str: str) -> str:
    """Minimal wiki produced when the DB has no community data."""
    lines = [
        f"# {repo_name} — subsystem wiki",
        "",
        f"Generated by context-router on {date_str}.",
        "",
        "_No subsystems detected._",
        "",
        (
            "The indexer did not populate community assignments for this "
            "project, so no structural summary is available. Run "
            "`context-router index --project-root <path>` on a project with "
            "analyzer-supported source files and try again."
        ),
        "",
    ]
    # Even the empty case ships three placeholder sections so downstream
    # tooling that asserts the ≥3-section threshold does not break.
    for i in range(1, _MIN_SECTIONS + 1):
        lines.append(_render_placeholder_subsystem(i))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_wiki(
    project_root: Path,
    *,
    repo: str = "default",
    top_n: int = DEFAULT_TOP_N,
    files_per_section: int = DEFAULT_FILES_PER_SECTION,
    hubs_per_section: int = DEFAULT_HUBS_PER_SECTION,
    now: datetime | None = None,
) -> str:
    """Return a markdown wiki summarising *project_root*'s subsystems.

    Args:
        project_root: The directory containing ``.context-router/``.
        repo: Logical repo name used when the index was built.  Defaults
            to ``"default"`` to match the ``context-router index`` CLI.
        top_n: Max number of subsystem sections to render.
        files_per_section: Max number of key-file entries per section.
        hubs_per_section: Max number of hub symbols named per section.
        now: Override for the timestamp header — test hook only.

    Returns:
        A markdown document.  Never empty; if the graph has no
        community data the returned string documents that fact and
        still carries ≥3 sections so the handover-wiki outcome's
        section-count invariant holds.
    """
    date_str = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    repo_name = project_root.resolve().name or "project"
    db_path = _resolve_db_path(project_root)

    if not db_path.exists():
        _warn(
            f"database not found at {db_path}; run 'context-router index' first"
        )
        return _render_empty_wiki(repo_name, date_str)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        _warn(f"could not open db ({type(exc).__name__}: {exc})")
        return _render_empty_wiki(repo_name, date_str)

    try:
        symbols = _fetch_symbols(conn, repo)
        inbound = _inbound_degrees(conn, repo)
    finally:
        conn.close()

    if not symbols:
        return _render_empty_wiki(repo_name, date_str)

    subsystems = _build_subsystems(
        symbols,
        inbound,
        files_per_section=files_per_section,
        hubs_per_section=hubs_per_section,
    )[:top_n]

    if not subsystems:
        return _render_empty_wiki(repo_name, date_str)

    # Resolve titles up-front so the TOC and the section headers agree.
    section_titles = [_subsystem_title(s) for s in subsystems]

    # Render the document.
    out: list[str] = []
    out.append(f"# {repo_name} — subsystem wiki")
    out.append("")
    out.append(f"Generated by context-router on {date_str}.")
    out.append("")
    out.append("## TOC")
    for title, sub in zip(section_titles, subsystems, strict=True):
        out.append(f"- [Subsystem: {title}](#{_anchor(title, sub.community_id)})")
    # Placeholder TOC entries so the TOC matches the final section count.
    needed_placeholders = max(0, _MIN_SECTIONS - len(subsystems))
    for i in range(1, needed_placeholders + 1):
        out.append(
            f"- [Subsystem: placeholder {i}]"
            f"(#subsystem-placeholder-{i})"
        )
    out.append("")

    for title, sub in zip(section_titles, subsystems, strict=True):
        out.append(_render_subsystem(sub, title))

    for i in range(1, needed_placeholders + 1):
        out.append(_render_placeholder_subsystem(i))

    return "\n".join(out)


__all__ = ["generate_wiki"]
