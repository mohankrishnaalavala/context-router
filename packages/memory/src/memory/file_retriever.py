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
    stale: bool = False
    staleness_reason: str | None = None
    source_repo: str = "local"


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
    federated_roots: "list[tuple[str, Path]] | None" = None,
) -> list[MemoryHit]:
    """Return top-k observations from ``memory_dir/observations/`` ranked by BM25 + recency.

    Algorithm:
    1. Scan all ``.md`` files in ``memory_dir/observations/`` (plus any federated repos).
    2. Parse YAML frontmatter and body from each file.
    3. Score with SQLite FTS5 BM25 over ``(id, body)`` text across all sources combined.
    4. Multiply BM25 score by a recency boost: ``1 / (1 + days**0.5)``.
    5. Sort descending by final score and return the top-k hits.
    6. Check staleness of top-k hits via git ls-files; set hit.stale when a path is missing.
    7. If no ``.md`` files exist, return ``[]``.
    8. If the query contains no valid FTS5 tokens, fall back to recency-only sorting.

    Args:
        query: Free-text query string.
        memory_dir: The ``.context-router/memory`` directory.
        k: Maximum number of hits to return.
        project_root: Optional path to the project root used to classify
            each hit's provenance via git (committed/staged/branch_local).
            When omitted, all hits default to ``provenance="committed"``.
            On the main branch, branch_local and staged hits are filtered out.
        federated_roots: Optional list of ``(repo_name, repo_root)`` tuples for
            cross-repo memory federation. Only **committed** observations are
            included from sibling repos. Each federated hit carries
            ``source_repo=repo_name``.

    Returns:
        List of :class:`MemoryHit` objects, most relevant first.
    """
    import sys

    obs_dir = memory_dir / "observations"
    if not obs_dir.exists():
        return []

    md_files = sorted(obs_dir.glob("*.md"))
    if not md_files and not federated_roots:
        return []

    # --- Parse all files ---------------------------------------------------
    # Each record: (fts_key, stem, created_at, files_touched, task, body_text, source_repo, obs_dir)
    # fts_key is unique across all sources; stem is the original file stem.
    DocRecord = tuple[str, str, datetime, list[str], str, str, str, Path]
    docs: list[DocRecord] = []

    for md_path in md_files:
        fm, body = _parse_md(md_path)
        created_at = _parse_created_at(fm)
        files_touched: list[str] = []
        raw_ft = fm.get("files_touched", [])
        if isinstance(raw_ft, list):
            files_touched = [str(f) for f in raw_ft]
        task = str(fm.get("task", ""))
        docs.append((md_path.stem, md_path.stem, created_at, files_touched, task, body, "local", obs_dir))

    # --- Collect federated observations (committed at HEAD only) ---
    # Use git ls-tree HEAD rather than git ls-files so that staged-but-uncommitted
    # observations in sibling repos are never federated (design spec §4.4).
    if federated_roots:
        import subprocess as _subproc
        for repo_name, sibling_root in federated_roots:
            sibling_obs_dir = sibling_root / ".context-router" / "memory" / "observations"
            if not sibling_obs_dir.is_dir():
                print(
                    f"WARN: repo {repo_name} has no memory; skipping federation",
                    file=sys.stderr,
                )
                continue
            try:
                _lsres = _subproc.run(
                    ["git", "ls-tree", "-r", "HEAD", "--name-only"],
                    cwd=str(sibling_root),
                    capture_output=True, text=True, timeout=5,
                )
                if _lsres.returncode != 0:
                    print(
                        f"WARN: repo {repo_name} memory unreadable; skipping federation",
                        file=sys.stderr,
                    )
                    continue
                committed_at_head: set[str] = set(_lsres.stdout.splitlines())
            except Exception:  # noqa: BLE001
                print(
                    f"WARN: repo {repo_name} memory unreadable; skipping federation",
                    file=sys.stderr,
                )
                continue
            for md_path in sorted(sibling_obs_dir.glob("*.md")):
                rel_path = str(md_path.relative_to(sibling_root))
                if rel_path not in committed_at_head:
                    continue  # staged-only or branch_local — must not federate
                fm, body = _parse_md(md_path)
                created_at = _parse_created_at(fm)
                raw_ft2 = fm.get("files_touched", [])
                ft2: list[str] = [str(f) for f in raw_ft2] if isinstance(raw_ft2, list) else []
                task2 = str(fm.get("task", ""))
                # Use prefixed key to guarantee uniqueness across repos
                fts_key = f"fed__{repo_name}__{md_path.stem}"
                docs.append((fts_key, md_path.stem, created_at, ft2, task2, body, repo_name, sibling_obs_dir))

    if not docs:
        return []

    # --- BM25 via SQLite FTS5 in-memory ------------------------------------
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE VIRTUAL TABLE docs USING fts5"
        "(id UNINDEXED, body, tokenize='porter ascii')"
    )
    rows = []
    for fts_key, _stem, _created_at, _files_touched, _task, body_text, _src, _obs_dir in docs:
        fts_body = fts_key + " " + body_text
        rows.append((fts_key, fts_body))
    conn.executemany("INSERT INTO docs (id, body) VALUES (?, ?)", rows)

    # Attempt BM25 query; fall back to recency-only on FTS syntax errors.
    bm25_scores: dict[str, float] = {}
    use_bm25 = True
    if query and query.strip():
        try:
            safe_query = query.strip()
            cursor = conn.execute(
                "SELECT id, bm25(docs) FROM docs WHERE docs MATCH ? ORDER BY bm25(docs)",
                (safe_query,),
            )
            for row in cursor.fetchall():
                doc_id, raw_score = row
                bm25_scores[doc_id] = -float(raw_score)
        except sqlite3.OperationalError:
            use_bm25 = False
    else:
        use_bm25 = False

    conn.close()

    # --- Combine BM25 + recency boost and sort -----------------------------
    # Matched docs score in [1.0, +inf); unmatched score in (0, 1.0).
    hits: list[MemoryHit] = []
    for fts_key, stem, created_at, files_touched, task, body_text, source_repo, hit_obs_dir in docs:
        boost = _recency_boost(created_at)

        if use_bm25:
            raw = bm25_scores.get(fts_key, 0.0)
            score = (1.0 + raw * boost) if raw > 0.0 else boost
        else:
            score = boost

        body_stripped = body_text.lstrip()
        excerpt = body_stripped[:200].rstrip()

        hits.append(
            MemoryHit(
                id=stem,
                path=hit_obs_dir / f"{stem}.md",
                excerpt=excerpt,
                score=score,
                files_touched=files_touched,
                task=task,
                source_repo=source_repo,
            )
        )

    # --- Classify local provenance and filter on main branch ---
    if project_root is not None:
        prov_map = _classify_memory_files(obs_dir, project_root)
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
            if hit.source_repo == "local":
                prov = prov_map.get(hit.id, "committed")
                hit.provenance = prov
                if on_main and prov != "committed":
                    continue
            # Federated hits are already committed-only (filtered above)
            filtered_hits.append(hit)
        hits = filtered_hits

    hits.sort(key=lambda h: h.score, reverse=True)
    top_hits = hits[:k]

    # --- Staleness check on top-k hits ---
    if project_root is not None and top_hits:
        from memory.staleness import ObservationStalenessChecker
        checker = ObservationStalenessChecker()
        all_files = [f for hit in top_hits for f in hit.files_touched]
        checker.check_batch(all_files, project_root)
        for hit in top_hits:
            is_stale, reason = checker.check(hit.files_touched, project_root)
            if is_stale:
                hit.stale = True
                hit.staleness_reason = reason
                print(
                    f"WARN: memory hit {hit.id} may be stale ({reason})",
                    file=sys.stderr,
                )

    return top_hits
