"""context-router memory command — manages durable session observations."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

memory_app = typer.Typer(help="Manage durable session memory (observations).")


def _open_store(project_root: str) -> tuple["ObservationStore", "Database"]:
    """Open the database and return (ObservationStore, Database).

    Caller must close the Database.
    """
    from core.orchestrator import _find_project_root
    from memory.store import ObservationStore
    from storage_sqlite.database import Database

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    db_path = root / ".context-router" / "context-router.db"
    if not db_path.exists():
        typer.echo(
            "No index found. Run 'context-router init' and 'context-router index' first.",
            err=True,
        )
        raise typer.Exit(1)
    db = Database(db_path)
    db.initialize()
    return ObservationStore(db), db


@memory_app.command("add")
def add(
    from_session: Annotated[
        str,
        typer.Option("--from-session", help="Path to session JSON file."),
    ] = "",
    stdin: Annotated[
        bool,
        typer.Option("--stdin", help="Read session JSON from stdin instead of a file."),
    ] = False,
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Add observations from a session JSON file or stdin to durable memory.

    Provide exactly one of --from-session PATH or --stdin.  The input must be
    a JSON object or array matching the Observation schema (summary field is
    required; all others are optional).

    Exit codes:
      0 — success
      1 — file not found, database not initialised, or no input source given
      2 — invalid JSON or schema
    """
    if stdin:
        session_json = sys.stdin.read()
    elif from_session:
        session_path = Path(from_session)
        if not session_path.exists():
            typer.echo(f"Session file not found: {from_session}", err=True)
            raise typer.Exit(1)
        session_json = session_path.read_text(encoding="utf-8")
    else:
        typer.echo("Provide --from-session PATH or --stdin.", err=True)
        raise typer.Exit(1)

    store, db = _open_store(project_root)
    try:
        ids = store.add_from_session_json(session_json)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(2)
    finally:
        db.close()

    if json_output:
        import json
        typer.echo(json.dumps({"added": len(ids), "ids": ids}))
    else:
        typer.echo(f"Added {len(ids)} observation(s) to memory.")


@memory_app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
    workspace: Annotated[
        bool,
        typer.Option("--workspace", help="Search across all workspace repos (committed observations only)."),
    ] = False,
) -> None:
    """Search stored observations by keyword.

    With --workspace, searches memory from all repos declared in workspace.yaml.
    Results are labeled with source_repo. Only committed observations federate.

    Exit codes:
      0 — success (even if no results)
      1 — database not initialised
    """
    from core.orchestrator import _find_project_root
    from memory.file_retriever import retrieve_observations

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    memory_dir = root / ".context-router" / "memory"

    fed_roots = _load_federated_roots(project_root) if workspace else []
    hits = retrieve_observations(query, memory_dir, k=20, project_root=root, federated_roots=fed_roots or None)

    if json_output:
        import json
        typer.echo(json.dumps(
            [
                {
                    "id": h.id,
                    "excerpt": h.excerpt,
                    "score": round(h.score, 4),
                    "files_touched": h.files_touched,
                    "task": h.task,
                    "provenance": h.provenance,
                    "source_repo": h.source_repo,
                    "stale": h.stale,
                    "staleness_reason": h.staleness_reason,
                }
                for h in hits
            ],
            indent=2,
        ))
        return

    if not hits:
        typer.echo("No observations found.")
        return

    for h in hits:
        repo_tag = f" [{h.source_repo}]" if h.source_repo != "local" else ""
        stale_tag = " [STALE]" if h.stale else ""
        typer.echo(f"  [{h.task or 'general'}]{repo_tag}{stale_tag} {h.excerpt[:80]}")


def _find_memory_dir(project_root: str) -> Path:
    """Resolve .context-router/memory from project_root or cwd."""
    from core.orchestrator import _find_project_root
    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    return root / ".context-router" / "memory"


def _load_federated_roots(project_root: str) -> "list[tuple[str, Path]]":
    """Return [(name, path), ...] for sibling repos from workspace.yaml.

    Emits a stderr warning and returns [] when workspace.yaml is missing.
    """
    from core.orchestrator import _find_project_root
    from workspace.loader import WorkspaceLoader

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    ws = WorkspaceLoader.load(root)
    if ws is None:
        typer.echo("WARN: --workspace has no effect; no workspace.yaml found", err=True)
        return []
    return [(repo.name, repo.path) for repo in ws.repos if Path(repo.path).resolve() != root.resolve()]


def _require_git(project_root: str) -> Path:
    """Return the repo root or exit 1 with a message if git is unavailable."""
    import subprocess
    from core.orchestrator import _find_project_root
    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            typer.echo("git is required for staleness detection", err=True)
            raise typer.Exit(1)
    except FileNotFoundError:
        typer.echo("git is required for staleness detection", err=True)
        raise typer.Exit(1)
    return root


@memory_app.command("stale")
def stale(
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List observations whose files_touched paths are absent from git HEAD.

    Checks each observation's files_touched list against git ls-files. Reports
    missing_file (hard stale), renamed (path changed), or dormant (>90d old,
    never surfaced in a pack).

    Exit codes:
      0 — success (even if no stale observations)
      1 — git unavailable or not a git repository
    """
    import json as _json
    from datetime import datetime, timezone
    from memory.staleness import ObservationStalenessChecker

    root = _require_git(project_root)
    memory_dir = root / ".context-router" / "memory"
    obs_dir = memory_dir / "observations"

    if not obs_dir.exists():
        if json_output:
            typer.echo(_json.dumps([]))
        else:
            typer.echo("No observations found.")
        return

    from memory.file_retriever import _parse_md, _parse_created_at

    checker = ObservationStalenessChecker()
    stale_results: list[dict] = []
    now = datetime.now(tz=timezone.utc)

    md_files = sorted(obs_dir.glob("*.md"))
    # Pre-populate cache with all files_touched across all observations
    all_files: list[str] = []
    parsed: list[tuple[Path, dict, str]] = []
    for md_path in md_files:
        fm, body = _parse_md(md_path)
        parsed.append((md_path, fm, body))
        raw_ft = fm.get("files_touched", [])
        if isinstance(raw_ft, list):
            all_files.extend(str(f) for f in raw_ft)
    checker.check_batch(all_files, root)

    for md_path, fm, _body in parsed:
        created_at = _parse_created_at(fm)
        raw_ft = fm.get("files_touched", [])
        files_touched: list[str] = [str(f) for f in raw_ft] if isinstance(raw_ft, list) else []
        is_stale, reason = checker.check(files_touched, root, created_at)
        if is_stale or (reason and reason.startswith("dormant")):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age_days = (now - created_at).days
            severity = reason.split(":")[0] if reason else "unknown"
            path_hint = reason.split(": ", 1)[1] if ": " in reason else ""
            stale_results.append({
                "id": md_path.stem,
                "severity": severity,
                "path": path_hint,
                "age_days": age_days,
                "is_stale": is_stale,
            })

    if json_output:
        typer.echo(_json.dumps(stale_results, indent=2))
        return

    if not stale_results:
        typer.echo("No stale observations found.")
        return

    typer.echo(f"{len(stale_results)} stale observation(s):")
    for r in stale_results:
        marker = "[STALE]" if r["is_stale"] else "[dormant]"
        typer.echo(f"  {marker} {r['id']}  severity={r['severity']}  path={r['path']}  age={r['age_days']}d")


@memory_app.command("prune")
def prune(
    stale_flag: Annotated[
        bool,
        typer.Option("--stale", help="Remove observations with missing_file or renamed severity."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview what would be removed without deleting."),
    ] = False,
    archive: Annotated[
        bool,
        typer.Option("--archive", help="Move to .context-router/memory/archived/ instead of deleting."),
    ] = False,
    severity: Annotated[
        str,
        typer.Option("--severity", help="Filter by severity: missing_file or renamed."),
    ] = "",
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
) -> None:
    """Remove or archive stale observations.

    --stale removes observations whose files_touched paths are absent from HEAD.
    Only hard-stale severities (missing_file, renamed) are removed; dormant
    observations are never auto-removed.

    Exit codes:
      0 — success
      1 — git unavailable or not a git repository
    """
    import shutil
    from memory.staleness import ObservationStalenessChecker
    from memory.file_retriever import _parse_md, _parse_created_at

    if not stale_flag:
        typer.echo("WARN: --stale has no effect without any stale observations", err=True)
        return

    root = _require_git(project_root)
    memory_dir = root / ".context-router" / "memory"
    obs_dir = memory_dir / "observations"
    archive_dir = memory_dir / "archived"

    if not obs_dir.exists():
        typer.echo("No observations found.")
        return

    checker = ObservationStalenessChecker()
    md_files = sorted(obs_dir.glob("*.md"))
    all_files: list[str] = []
    parsed: list[tuple[Path, dict]] = []
    for md_path in md_files:
        fm, _body = _parse_md(md_path)
        parsed.append((md_path, fm))
        raw_ft = fm.get("files_touched", [])
        if isinstance(raw_ft, list):
            all_files.extend(str(f) for f in raw_ft)
    checker.check_batch(all_files, root)

    to_remove: list[Path] = []
    for md_path, fm in parsed:
        created_at = _parse_created_at(fm)
        raw_ft = fm.get("files_touched", [])
        files_touched: list[str] = [str(f) for f in raw_ft] if isinstance(raw_ft, list) else []
        is_stale, reason = checker.check(files_touched, root, created_at)
        if not is_stale:
            continue
        sev = reason.split(":")[0] if reason else "unknown"
        if severity and sev != severity:
            continue
        to_remove.append(md_path)

    if not to_remove:
        typer.echo("WARN: --stale has no effect without any stale observations", err=True)
        return

    if dry_run:
        typer.echo(f"Would remove {len(to_remove)} observation(s):")
        for p in to_remove:
            typer.echo(f"  {p.stem}")
        return

    if archive:
        archive_dir.mkdir(parents=True, exist_ok=True)
        for p in to_remove:
            shutil.move(str(p), str(archive_dir / p.name))
        typer.echo(f"Archived {len(to_remove)} observation(s) to {archive_dir}.")
    else:
        for p in to_remove:
            p.unlink()
        typer.echo(f"Removed {len(to_remove)} stale observation(s).")


@memory_app.command("list")
def list_memory(
    sort: Annotated[
        str,
        typer.Option("--sort", help="Sort order: freshness (default), confidence, or recent."),
    ] = "freshness",
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of observations to show."),
    ] = 20,
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
    workspace: Annotated[
        bool,
        typer.Option("--workspace", help="List observations from all workspace repos (grouped by source_repo)."),
    ] = False,
) -> None:
    """List stored observations sorted by freshness, confidence, or recency.

    freshness — effective_confidence (time-decay × quality × access boost)
    confidence — raw stored confidence_score
    recent     — most recently created first

    With --workspace, includes observations from all workspace repos, grouped by source_repo.
    Only committed observations are shown from sibling repos.

    Exit codes:
      0 — success
      1 — database not initialised
    """
    from memory.freshness import effective_confidence
    from memory.file_retriever import _parse_md, _parse_created_at

    # --- Workspace: enumerate sibling .md files (committed only) ---
    fed_roots = _load_federated_roots(project_root) if workspace else []
    fed_hits: list[dict] = []
    if fed_roots:
        from memory.file_retriever import _classify_memory_files
        for repo_name, sibling_root in fed_roots:
            sibling_obs_dir = Path(sibling_root) / ".context-router" / "memory" / "observations"
            if not sibling_obs_dir.is_dir():
                typer.echo(f"WARN: repo {repo_name} has no memory; skipping", err=True)
                continue
            try:
                prov_map = _classify_memory_files(sibling_obs_dir, Path(sibling_root))
            except Exception:  # noqa: BLE001
                typer.echo(f"WARN: repo {repo_name} memory unreadable; skipping", err=True)
                continue
            for md_path in sorted(sibling_obs_dir.glob("*.md")):
                if prov_map.get(md_path.stem, "committed") != "committed":
                    continue
                fm, body = _parse_md(md_path)
                created_at = _parse_created_at(fm)
                body_stripped = body.lstrip()
                fed_hits.append({
                    "id": md_path.stem,
                    "source_repo": repo_name,
                    "summary": body_stripped[:80],
                    "task": str(fm.get("task", "")),
                    "created_at": str(created_at.date()),
                })

    store, db = _open_store(project_root)
    try:
        if sort == "freshness":
            observations = store.list_by_freshness()[:limit]
        elif sort == "confidence":
            observations = sorted(
                store._get_all(), key=lambda o: o.confidence_score, reverse=True
            )[:limit]
        else:  # "recent" or any other value
            observations = store._get_all()[:limit]
    finally:
        db.close()

    if json_output:
        import json
        local_out = [
            {**r.model_dump(mode="json"), "effective_confidence": round(effective_confidence(r), 4), "source_repo": "local"}
            for r in observations
        ]
        typer.echo(json.dumps({"local": local_out, "federated": fed_hits}, indent=2))
        return

    if not observations and not fed_hits:
        typer.echo("No observations found.")
        return

    for obs in observations:
        eff = round(effective_confidence(obs), 3)
        age_days = (import_datetime() - obs.timestamp).days
        typer.echo(
            f"  [local] [{obs.task_type or 'general'}] {obs.summary[:70]}"
            f"  (eff={eff}, age={age_days}d)"
        )

    if fed_hits:
        typer.echo(f"\n--- Federated observations ({len(fed_hits)} across {len(fed_roots)} repos) ---")
        for h in fed_hits[:limit]:
            typer.echo(f"  [{h['source_repo']}] [{h['task'] or 'general'}] {h['summary']}")


def import_datetime() -> "datetime":
    from datetime import UTC, datetime
    return datetime.now(UTC)


@memory_app.command("capture")
def capture(
    summary: Annotated[str, typer.Argument(help="One-line task summary.")],
    task_type: Annotated[
        str,
        typer.Option("--task-type", help="Task type (e.g. debug, implement, commit, handover)."),
    ] = "general",
    files: Annotated[
        str,
        typer.Option("--files", help="Space-separated file paths touched during the task."),
    ] = "",
    commit: Annotated[
        str,
        typer.Option("--commit", help="Git commit SHA associated with this observation."),
    ] = "",
    fix: Annotated[
        str,
        typer.Option("--fix", help="Short description of the fix or resolution."),
    ] = "",
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Capture a task observation directly from command-line arguments.

    Unlike 'memory add' which imports a JSON file, 'capture' lets adapters
    and hooks persist a normalized observation in one command.  Guardrails
    are applied: duplicate tasks (same type + summary) are silently skipped,
    and secret values in --files are not exposed.

    Example::

        context-router memory capture "fixed auth bug" \\
          --task-type debug --files "auth.py tests/test_auth.py" \\
          --commit abc1234 --fix "added null-check on token"

    Exit codes:
      0 — success (or silently skipped duplicate)
      1 — database not initialised
    """
    from contracts.models import Observation
    from core.orchestrator import _find_project_root
    from memory.capture import capture_observation
    from memory.file_writer import MemoryFileWriter

    files_list = [f for f in files.split() if f] if files else []

    obs = Observation(
        summary=summary,
        task_type=task_type,
        files_touched=files_list,
        commit_sha=commit,
        fix_summary=fix,
    )

    store, db = _open_store(project_root)
    try:
        row_id = capture_observation(store, obs, min_files=0)
    finally:
        db.close()

    # Also write a git-tracked .md file when the observation passes the write
    # gate (summary >= 60 chars, files_touched non-empty, task_type != scratch).
    # This mirrors the MCP save_observation behaviour so the two surfaces stay
    # consistent.  A failed write gate is NOT a hard error — it just means the
    # observation lives only in SQLite (e.g. it was too short).
    # Pre-check the gate so the writer never emits its own stderr warning
    # during `capture`; callers that only want the SQLite record (e.g. very
    # short summaries) are not surprised by unexpected stderr output.
    md_path: str | None = None
    if row_id is not None:
        root = Path(project_root) if project_root else _find_project_root(Path.cwd())
        memory_dir = root / ".context-router" / "memory"
        writer = MemoryFileWriter(memory_dir)
        if not writer._check_gate(obs):
            file_result = writer.write_observation(obs)
            if file_result.written:
                writer.update_index()
                md_path = str(file_result.path)

    if json_output:
        import json
        if row_id is None:
            typer.echo(json.dumps({"captured": False, "reason": "duplicate"}))
        else:
            result: dict = {"captured": True, "id": row_id}
            if md_path:
                result["file"] = md_path
            typer.echo(json.dumps(result))
    else:
        if row_id is None:
            typer.echo("Skipped: duplicate observation (same task type + summary).")
        else:
            typer.echo(f"Captured observation #{row_id}.")


@memory_app.command("show")
def show(
    id: Annotated[str, typer.Argument(help="Observation ID (stem of the .md file).")],
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the full contents of a single observation by ID.

    Searches {project_root}/.context-router/memory/observations/ for {id}.md.
    If an exact match is not found, falls back to any file whose stem starts
    with the given id (partial prefix match).

    Exit codes:
      0 — found
      1 — not found or directory not initialised
    """
    import json as _json

    from core.orchestrator import _find_project_root

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    observations_dir = root / ".context-router" / "memory" / "observations"

    if not observations_dir.exists():
        typer.echo(f"No observation found with id: {id}", err=True)
        raise typer.Exit(1)

    # Exact match first
    candidate = observations_dir / f"{id}.md"
    if not candidate.exists():
        # Partial prefix match — pick the first alphabetically
        matches = sorted(observations_dir.glob(f"{id}*.md"))
        if not matches:
            typer.echo(f"No observation found with id: {id}", err=True)
            raise typer.Exit(1)
        candidate = matches[0]

    content = candidate.read_text(encoding="utf-8")

    if not json_output:
        typer.echo(content, nl=False)
        return

    # Parse YAML frontmatter for --json output
    try:
        import yaml  # type: ignore[import-untyped]
        _yaml_available = True
    except ImportError:
        _yaml_available = False

    parts = content.split("---\n", 2)
    if len(parts) >= 3 and _yaml_available:
        frontmatter_text = parts[1]
        body = parts[2]
        fm = yaml.safe_load(frontmatter_text) or {}
    else:
        # Fallback: surface raw content as body only
        fm = {}
        body = content

    result = {
        "id": fm.get("id", candidate.stem),
        "type": fm.get("type", "observation"),
        "task": fm.get("task", ""),
        "files_touched": fm.get("files_touched", []),
        "created_at": str(fm.get("created_at", "")),
        "author": fm.get("author", ""),
        "body": body.strip(),
    }
    typer.echo(_json.dumps(result, indent=2))


@memory_app.command("migrate-from-sqlite")
def migrate_from_sqlite(
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be written without writing files."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Migrate all SQLite observations to git-tracked Markdown files.

    Reads every observation from the SQLite ObservationStore and writes each
    one as a .md file under .context-router/memory/observations/.  The write
    gate inside MemoryFileWriter silently skips observations that are too
    short, have no files_touched, or are tagged as scratch work.

    After writing, MEMORY.md is regenerated as an index of all observation
    files.

    Exit codes:
      0 — success
      1 — database not found
    """
    import json as _json

    from core.orchestrator import _find_project_root
    from memory.file_writer import MemoryFileWriter

    root = Path(project_root) if project_root else _find_project_root(Path.cwd())
    memory_dir = root / ".context-router" / "memory"

    store, db = _open_store(project_root)
    try:
        all_obs = store._get_all()
    finally:
        db.close()

    total = len(all_obs)
    migrated = 0
    skipped = 0

    writer = MemoryFileWriter(memory_dir)

    for obs in all_obs:
        # Check write gate without writing when --dry-run
        rejection = writer._check_gate(obs)
        if rejection:
            skipped += 1
            if not json_output:
                typer.echo(f"  skip [{obs.summary[:50]}]: {rejection}", err=True)
            continue

        if dry_run:
            typer.echo(f"  would write: {obs.summary[:60]}")
            migrated += 1
            continue

        result = writer.write_observation(obs)
        if result.written:
            migrated += 1
        else:
            skipped += 1

    if not dry_run and migrated > 0:
        writer.update_index()

    summary_line = f"Migrated {migrated} / {total} observations ({skipped} skipped by write gate)"
    if dry_run:
        summary_line = f"[dry-run] Would migrate {migrated} / {total} observations ({skipped} skipped by write gate)"

    if json_output:
        typer.echo(_json.dumps({"migrated": migrated, "skipped": skipped, "total": total}))
    else:
        typer.echo(summary_line)


@memory_app.command("export")
def export_memory(
    output: Annotated[
        str,
        typer.Option("--output", help="Output file path. Defaults to .context-router/export/memory.md."),
    ] = "",
    sort: Annotated[
        str,
        typer.Option("--sort", help="Sort order: freshness (default), confidence, or recent."),
    ] = "freshness",
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of observations to export."),
    ] = 100,
    redacted: Annotated[
        bool,
        typer.Option("--redacted", help="Strip file paths, commands, and commit SHAs for safe sharing."),
    ] = False,
    project_root: Annotated[
        str,
        typer.Option("--project-root", help="Project root. Auto-detected when omitted."),
    ] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Export observations to a Markdown file for team sharing.

    Without --redacted, the export includes file paths, commands, and commit SHAs.
    With --redacted, only the summary and fix_summary are exported — safe for
    sharing in public repositories or team wikis.

    Exit codes:
      0 — success
      1 — database not initialised
    """
    from core.orchestrator import _find_project_root
    from memory.export import export_observations
    from memory.freshness import effective_confidence

    store, db = _open_store(project_root)
    try:
        if sort == "freshness":
            observations = store.list_by_freshness()[:limit]
        elif sort == "confidence":
            observations = sorted(
                store._get_all(), key=lambda o: o.confidence_score, reverse=True
            )[:limit]
        else:
            observations = store._get_all()[:limit]
    finally:
        db.close()

    # Determine output path
    if output:
        out_path = Path(output)
    else:
        from core.orchestrator import _find_project_root
        root = Path(project_root) if project_root else _find_project_root(Path.cwd())
        out_path = root / ".context-router" / "export" / "memory.md"

    count = export_observations(observations, out_path, redact=redacted)

    if json_output:
        import json
        typer.echo(json.dumps({"exported": count, "path": str(out_path)}))
    else:
        tag = " (redacted)" if redacted else ""
        typer.echo(f"Exported {count} observation(s) to {out_path}{tag}")
