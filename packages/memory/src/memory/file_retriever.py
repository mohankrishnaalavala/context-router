"""BM25 + recency retrieval over git-tracked .md observation files.

Scans ``.context-router/memory/observations/*.md``, builds an in-memory
SQLite FTS5 index for BM25 scoring, applies a recency boost, and returns
the top-k hits ranked by ``bm25_score * recency_boost``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MemoryHit:
    """A single observation hit returned by :func:`retrieve_observations`.

    Attributes:
        id: Stem of the .md filename (e.g. ``2026-04-24-fixed-checkout-dedup``).
        path: Absolute path of the .md file.
        excerpt: First 200 characters of the summary body.
        score: BM25 score multiplied by the recency boost factor.
        files_touched: List of file paths from the YAML frontmatter.
        task: Task type string from the YAML frontmatter.
    """

    id: str
    path: Path
    excerpt: str
    score: float
    files_touched: list[str] = field(default_factory=list)
    task: str = ""
    provenance: str = "committed"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_md(path: Path) -> tuple[dict, str]:
    """Parse a frontmatter .md file into ``(frontmatter_dict, body_text)``.

    The file format is::

        ---
        key: value
        ...
        ---

        <body text>

    If the file does not have proper frontmatter, an empty dict and the full
    file text are returned.  Never raises; returns empty results on IO errors.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}, ""

    # Split on the first two '---' delimiter lines.
    # Expected structure: ["", " yaml block ", " body "]
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return {}, text

    yaml_block = parts[1]
    body = parts[2]

    # Lazy import yaml to avoid module-level import cost when the caller
    # never needs frontmatter parsing (e.g. import-only usage).
    try:
        import yaml  # type: ignore[import-untyped]
        fm = yaml.safe_load(yaml_block) or {}
    except Exception:  # noqa: BLE001
        fm = {}

    if not isinstance(fm, dict):
        fm = {}

    return fm, body


def _parse_created_at(fm: dict) -> datetime:
    """Extract created_at from frontmatter, falling back to epoch on failure."""
    raw = fm.get("created_at")
    if raw is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if isinstance(raw, datetime):
        # PyYAML may parse ISO-8601 datetimes natively.
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw
    # String fallback — strip trailing fractional timezone like +00:00
    try:
        s = str(raw).strip()
        # fromisoformat handles "2026-04-24T13:58:00+00:00" in Python 3.11+.
        # For 3.9/3.10 compatibility we normalise the offset manually.
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _recency_boost(created_at: datetime) -> float:
    """Return a boost in (0, 1] that decays as observations age.

    Formula: ``1 / (1 + days_since**0.5)``
    A freshly written observation (days=0) gets boost 1.0; one written
    1 year ago (~365 days) gets ~0.05.
    """
    now = datetime.now(tz=timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    delta = now - created_at
    days = max(delta.total_seconds() / 86400.0, 0.0)
    return 1.0 / (1.0 + days ** 0.5)


def _classify_memory_files(obs_dir: Path, project_root: Path) -> dict[str, str]:
    """Classify .md files in obs_dir as 'committed', 'staged', or 'branch_local'.

    Runs two git subprocess calls:
    - ``git ls-files`` → committed files
    - ``git diff --cached --name-only`` → staged-but-uncommitted files
    Files in obs_dir that appear in neither set are 'branch_local'.

    Returns a dict mapping file stem (without .md) to provenance string.
    Falls back to marking all files as 'committed' on any error (git absent,
    not a repo, etc.) so the function always degrades gracefully.
    """
    import subprocess

    provenance: dict[str, str] = {}
    try:
        result_committed = subprocess.run(
            ["git", "ls-files", str(obs_dir)],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Non-zero exit code (e.g. 128 = not a git repo) → graceful fallback
        if result_committed.returncode != 0:
            return {}
        committed_paths = set(result_committed.stdout.splitlines())

        result_staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        staged_paths = set(result_staged.stdout.splitlines())
    except Exception:  # noqa: BLE001
        # git absent, not a repo, timeout — treat all as committed
        return {}

    for md_path in obs_dir.glob("*.md"):
        rel = str(md_path.relative_to(project_root)) if project_root else md_path.name
        if rel in committed_paths:
            provenance[md_path.stem] = "committed"
        elif rel in staged_paths:
            provenance[md_path.stem] = "staged"
        else:
            provenance[md_path.stem] = "branch_local"
    return provenance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve_observations(
    query: str,
    memory_dir: Path,
    k: int = 8,
    project_root: Path | None = None,
) -> list[MemoryHit]:
    """Return top-k observations from ``memory_dir/observations/`` ranked by BM25 + recency.

    Algorithm:
    1. Scan all ``.md`` files in ``memory_dir/observations/``.
    2. Parse YAML frontmatter and body from each file.
    3. Score with SQLite FTS5 BM25 over ``(id, body)`` text.
    4. Multiply BM25 score by a recency boost: ``1 / (1 + days**0.5)``.
    5. Sort descending by final score and return the top-k hits.
    6. If no ``.md`` files exist, return ``[]``.
    7. If the query contains no valid FTS5 tokens, fall back to recency-only
       sorting (all docs ranked purely by recency boost).

    Args:
        query: Free-text query string.
        memory_dir: The ``.context-router/memory`` directory.
        k: Maximum number of hits to return.
        project_root: Optional path to the project root used to classify
            each hit's provenance via git (committed/staged/branch_local).
            When omitted, all hits default to ``provenance="committed"``.
            On the main branch, branch_local and staged hits are filtered out.

    Returns:
        List of :class:`MemoryHit` objects, most relevant first.
    """
    obs_dir = memory_dir / "observations"
    if not obs_dir.exists():
        return []

    md_files = sorted(obs_dir.glob("*.md"))
    if not md_files:
        return []

    # --- Parse all files ---------------------------------------------------
    # docs: list of (stem, created_at, files_touched, task, body_text)
    docs: list[tuple[str, datetime, list[str], str, str]] = []
    for md_path in md_files:
        fm, body = _parse_md(md_path)
        created_at = _parse_created_at(fm)
        files_touched: list[str] = []
        raw_ft = fm.get("files_touched", [])
        if isinstance(raw_ft, list):
            files_touched = [str(f) for f in raw_ft]
        task = str(fm.get("task", ""))
        docs.append((md_path.stem, created_at, files_touched, task, body))

    # --- BM25 via SQLite FTS5 in-memory ------------------------------------
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE VIRTUAL TABLE docs USING fts5"
        "(id UNINDEXED, body, tokenize='porter ascii')"
    )
    rows = []
    for stem, _created_at, _files_touched, _task, body_text in docs:
        # body for FTS: combine stem + body so id tokens also score
        fts_body = stem + " " + body_text
        rows.append((stem, fts_body))
    conn.executemany("INSERT INTO docs (id, body) VALUES (?, ?)", rows)

    # Attempt BM25 query; fall back to recency-only on FTS syntax errors.
    bm25_scores: dict[str, float] = {}
    use_bm25 = True
    if query and query.strip():
        try:
            # Sanitise the query: FTS5 MATCH requires at least one valid token.
            # Escape special chars minimally: wrap in double quotes to treat as
            # a phrase, which handles most non-token input gracefully.
            safe_query = query.strip()
            cursor = conn.execute(
                "SELECT id, bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)",
                (safe_query,),
            )
            for row in cursor.fetchall():
                doc_id, raw_score = row
                # bm25() returns negative values; negate for positive "higher = better"
                bm25_scores[doc_id] = -float(raw_score)
        except sqlite3.OperationalError:
            # Query contained FTS5 syntax not recognized — fall back to recency
            use_bm25 = False
    else:
        use_bm25 = False

    conn.close()

    # --- Combine BM25 + recency boost and sort -----------------------------
    # When use_bm25 is True, matched docs always outrank non-matched docs.
    # We achieve this by placing matched doc scores in the range [1.0, +inf)
    # and non-matched doc scores in the range [0.0, 1.0), so the two groups
    # never interleave regardless of recency.
    hits: list[MemoryHit] = []
    for stem, created_at, files_touched, task, body_text in docs:
        boost = _recency_boost(created_at)  # in (0, 1]

        if use_bm25:
            raw = bm25_scores.get(stem, 0.0)
            if raw > 0.0:
                # Matched: score is 1 + (bm25 * boost). Always >= 1.0.
                score = 1.0 + raw * boost
            else:
                # Not matched: score is recency boost alone, in (0, 1).
                # These always rank below any matched doc.
                score = boost
        else:
            score = boost

        # Excerpt: first 200 chars of the body (strip leading whitespace/blank lines)
        body_stripped = body_text.lstrip()
        excerpt = body_stripped[:200].rstrip()

        hits.append(
            MemoryHit(
                id=stem,
                path=obs_dir / f"{stem}.md",
                excerpt=excerpt,
                score=score,
                files_touched=files_touched,
                task=task,
            )
        )

    # Classify provenance and optionally filter to committed-only on main branch
    if project_root is not None:
        prov_map = _classify_memory_files(obs_dir, project_root)
        # Determine if we're on main branch
        on_main = False
        try:
            import subprocess
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(project_root), capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            on_main = branch == "main"
        except Exception:  # noqa: BLE001
            pass

        filtered_hits = []
        for hit in hits:
            prov = prov_map.get(hit.id, "committed")  # default committed when not in map
            hit = MemoryHit(
                id=hit.id, path=hit.path, excerpt=hit.excerpt, score=hit.score,
                files_touched=hit.files_touched, task=hit.task, provenance=prov,
            )
            if on_main and prov != "committed":
                continue  # filter branch-local/staged on main checkout
            filtered_hits.append(hit)
        hits = filtered_hits

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]
